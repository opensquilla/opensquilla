from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest

from opensquilla.engine import Agent, AgentConfig, SubagentSpec
from opensquilla.engine.outcome import outcome_from_error
from opensquilla.engine.pricing import PriceEntry, ResolvedModelPrice
from opensquilla.engine.runtime import TurnRunner, _SelectorFallbackProvider
from opensquilla.engine.types import DoneEvent as AgentDone
from opensquilla.engine.types import ErrorEvent
from opensquilla.engine.usage_accounting import (
    UsageAccountingScope,
    UsageAccountingUnavailableError,
    UsageCallResult,
    UsageCallStart,
    UsageExecutionContext,
    account_provider_stream,
    bind_usage_accounting_scope,
    normalize_provider_usage,
    usd_to_nanos,
)
from opensquilla.provider import ChatConfig, Message
from opensquilla.provider import DoneEvent as ProviderDone
from opensquilla.provider import ErrorEvent as ProviderError
from opensquilla.provider import TextDeltaEvent as ProviderText
from opensquilla.session.manager import SessionManager
from opensquilla.session.storage import SessionStorage
from opensquilla.skills.meta.orchestrator import make_llm_chat_from_provider
from opensquilla.tools.types import CallerKind, ToolContext
from opensquilla.usage_reasons import (
    normalize_usage_unknown_reason,
    provider_error_usage_reason,
)


class _RecordingSink:
    def __init__(self) -> None:
        self.started: list[UsageCallStart] = []
        self.finalized: list[tuple[UsageCallStart, UsageCallResult]] = []
        self.unknown: list[tuple[UsageCallStart, str]] = []

    async def start(self, call: UsageCallStart) -> None:
        self.started.append(call)

    async def finalize(self, call: UsageCallStart, result: UsageCallResult) -> None:
        self.finalized.append((call, result))

    async def mark_unknown(self, call: UsageCallStart, reason: str) -> None:
        self.unknown.append((call, reason))


class _UnavailableSink(_RecordingSink):
    async def start(self, call: UsageCallStart) -> None:
        self.started.append(call)
        raise UsageAccountingUnavailableError("ledger busy")


class _DoneProvider:
    provider_name = "fake"

    def __init__(self, sink: _RecordingSink) -> None:
        self.sink = sink
        self.calls = 0

    def chat(
        self,
        messages: list[Message],
        tools: list[Any] | None = None,
        config: ChatConfig | None = None,
    ) -> AsyncIterator[Any]:
        del messages, tools, config
        # start() is a fail-closed barrier before provider.chat is invoked.
        assert len(self.sink.started) == self.calls + 1
        self.calls += 1
        return self._stream()

    async def _stream(self) -> AsyncIterator[Any]:
        yield ProviderText(text="ok")
        yield ProviderDone(
            input_tokens=11,
            output_tokens=3,
            cached_tokens=2,
            billed_cost=0.000000123,
            cost_source="provider_billed",
            model="model-a",
        )


class _ErrorProvider:
    provider_name = "fake"
    retry_failed_call_safe = False

    def __init__(self, code: str = "401") -> None:
        self.code = code

    def chat(
        self,
        messages: list[Message],
        tools: list[Any] | None = None,
        config: ChatConfig | None = None,
    ) -> AsyncIterator[Any]:
        del messages, tools, config
        return self._stream()

    async def _stream(self) -> AsyncIterator[Any]:
        yield ProviderError(message="denied", code=self.code)


class _BlockingProvider:
    provider_name = "fake"

    def __init__(self) -> None:
        self.entered = asyncio.Event()

    def chat(
        self,
        messages: list[Message],
        tools: list[Any] | None = None,
        config: ChatConfig | None = None,
    ) -> AsyncIterator[Any]:
        del messages, tools, config
        return self._stream()

    async def _stream(self) -> AsyncIterator[Any]:
        self.entered.set()
        await asyncio.Event().wait()
        if False:  # pragma: no cover - make this an async generator
            yield None


class _SequenceProvider:
    provider_name = "fake"

    def __init__(self, streams: list[list[Any]]) -> None:
        self.streams = streams
        self.calls = 0

    def chat(
        self,
        messages: list[Message],
        tools: list[Any] | None = None,
        config: ChatConfig | None = None,
    ) -> AsyncIterator[Any]:
        del messages, tools, config
        events = self.streams[self.calls]
        self.calls += 1
        return self._stream(events)

    async def _stream(self, events: list[Any]) -> AsyncIterator[Any]:
        for event in events:
            yield event


class _PhysicalLegProvider(_SequenceProvider):
    def __init__(self, name: str, events: list[Any]) -> None:
        super().__init__([events])
        self.provider_name = name


class _FallbackSelector:
    def __init__(self, fallback: Any) -> None:
        self._fallback = fallback
        self.active_provider_id = "openai"
        self.current_config = SimpleNamespace(model="primary-model")

    def next_fallback_after_failure(self, exc: Exception) -> Any:
        del exc
        self.active_provider_id = "anthropic"
        self.current_config = SimpleNamespace(model="fallback-model")
        return self._fallback


class _SingleProviderSelector:
    def __init__(self, provider: Any) -> None:
        self.provider = provider
        self.active_provider_id = "fake"
        self.current_config = SimpleNamespace(model="model-a")

    def clone(self) -> _SingleProviderSelector:
        return _SingleProviderSelector(self.provider)

    def resolve(self) -> Any:
        return self.provider

    def override_model(self, model: str) -> None:
        self.current_config = SimpleNamespace(model=model)


class _RecordingTracker:
    def __init__(self) -> None:
        self.rows: list[tuple[str, dict[str, Any]]] = []

    def add(self, session_key: str, **values: Any) -> None:
        self.rows.append((session_key, values))

    def session_checkpoint(self, session_key: str) -> None:
        del session_key
        return None

    def session_delta_snapshot(self, session_key: str, checkpoint: Any) -> None:
        del session_key, checkpoint
        return None

    def session_snapshot(self, session_key: str) -> None:
        del session_key
        return None

    def get(self, session_key: str) -> None:
        del session_key
        return None


def _context() -> UsageExecutionContext:
    return UsageExecutionContext(
        execution_id="turn-1",
        agent_run_id="run-1",
        turn_id="turn-1",
        session_id="session-1",
        session_epoch=7,
        agent_id="main",
        run_kind="webchat",
    )


@pytest.mark.asyncio
async def test_provider_call_is_started_before_chat_and_finalized_once() -> None:
    sink = _RecordingSink()
    provider = _DoneProvider(sink)
    agent = Agent(
        provider=provider,
        config=AgentConfig(max_iterations=1, provider_id="fake", model_id="model-a"),
        usage_event_sink=sink,
        usage_execution_context=_context(),
    )

    async for _ in agent.run_turn("hello"):
        pass

    assert provider.calls == 1
    assert [(call.execution_id, call.call_index) for call in sink.started] == [
        ("turn-1", 1)
    ]
    assert len(sink.finalized) == 1
    assert sink.unknown == []
    call, result = sink.finalized[0]
    assert call.event_id == sink.started[0].event_id
    assert call.session_epoch == 7
    assert result.billed_cost_nanos == 123
    assert result.estimated_cost_nanos == 0
    assert result.cost_source == "provider_billed"


@pytest.mark.asyncio
async def test_ledger_start_failure_is_retryable_and_withholds_provider_request() -> None:
    sink = _UnavailableSink()
    provider = _SequenceProvider([[ProviderDone()]])
    agent = Agent(
        provider=provider,
        config=AgentConfig(max_iterations=1),
        usage_event_sink=sink,
        usage_execution_context=_context(),
    )

    with pytest.raises(UsageAccountingUnavailableError, match="ledger busy"):
        async for _ in agent.run_turn("hello"):
            pass

    assert provider.calls == 0
    outcome = outcome_from_error(code=UsageAccountingUnavailableError.code)
    assert outcome.kind == "blocked"
    assert outcome.retryable is True


@pytest.mark.asyncio
async def test_provider_error_closes_started_call_as_unknown() -> None:
    sink = _RecordingSink()
    agent = Agent(
        provider=_ErrorProvider(),
        config=AgentConfig(max_iterations=1, max_provider_retries=0),
        usage_event_sink=sink,
        usage_execution_context=_context(),
    )

    async for _ in agent.run_turn("hello"):
        pass

    assert len(sink.started) == 1
    assert sink.finalized == []
    assert [(call.event_id, reason) for call, reason in sink.unknown] == [
        (sink.started[0].event_id, "provider_error:401")
    ]


@pytest.mark.asyncio
async def test_agent_does_not_persist_untrusted_provider_error_code() -> None:
    sink = _RecordingSink()
    agent = Agent(
        provider=_ErrorProvider("https://provider.invalid/error?key=sk-secret\nnext"),
        config=AgentConfig(max_iterations=1, max_provider_retries=0),
        usage_event_sink=sink,
        usage_execution_context=_context(),
    )

    async for _ in agent.run_turn("hello"):
        pass

    assert [reason for _, reason in sink.unknown] == ["provider_error"]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("401", "provider_error:401"),
        ("rate_limit_error", "provider_error:rate_limit"),
        ("timeout", "provider_error:timeout"),
        ("vendor_private_code", "provider_error"),
        ("https://provider.invalid/error", "provider_error"),
        ("sk-proj-secret-value", "provider_error"),
        ("401\nrequest-id", "provider_error"),
    ],
)
def test_provider_error_reason_uses_closed_taxonomy(value: str, expected: str) -> None:
    assert provider_error_usage_reason(value) == expected


def test_unknown_reason_normalizer_drops_exception_and_arbitrary_details() -> None:
    assert normalize_usage_unknown_reason("raised:SecretBearingException") == (
        "provider_exception"
    )
    assert normalize_usage_unknown_reason("arbitrary-third-party-value") == "usage_unknown"


@pytest.mark.asyncio
async def test_cancelled_provider_call_is_marked_unknown() -> None:
    sink = _RecordingSink()
    provider = _BlockingProvider()
    agent = Agent(
        provider=provider,
        config=AgentConfig(max_iterations=1),
        usage_event_sink=sink,
        usage_execution_context=_context(),
    )

    async def consume() -> None:
        async for _ in agent.run_turn("hello"):
            pass

    task = asyncio.create_task(consume())
    await asyncio.wait_for(provider.entered.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert len(sink.started) == 1
    assert sink.finalized == []
    assert len(sink.unknown) == 1
    assert sink.unknown[0][1] == "cancelled"


@pytest.mark.asyncio
async def test_retried_done_calls_get_monotonic_distinct_identities() -> None:
    sink = _RecordingSink()
    provider = _SequenceProvider(
        [
            [ProviderDone(input_tokens=2, output_tokens=0)],
            [ProviderText(text="ok"), ProviderDone(input_tokens=3, output_tokens=1)],
        ]
    )
    agent = Agent(
        provider=provider,
        config=AgentConfig(
            max_iterations=1,
            max_provider_retries=1,
            retry_base_backoff_ms=0,
            retry_max_backoff_ms=0,
        ),
        usage_event_sink=sink,
        usage_execution_context=_context(),
    )

    async for _ in agent.run_turn("hello"):
        pass

    assert provider.calls == 2
    assert [call.call_index for call in sink.started] == [1, 2]
    assert len({call.event_id for call in sink.started}) == 2
    assert [call.event_id for call, _ in sink.finalized] == [
        call.event_id for call in sink.started
    ]
    assert sink.unknown == []


@pytest.mark.asyncio
async def test_agent_does_not_promote_unverified_provider_cost_to_billed() -> None:
    provider = _SequenceProvider(
        [
            [
                ProviderText(text="ok"),
                ProviderDone(
                    input_tokens=10,
                    output_tokens=2,
                    billed_cost=99.0,
                    cost_source="provider_billed_unverified",
                    model="model-a",
                ),
            ]
        ]
    )
    agent = Agent(
        provider=provider,
        config=AgentConfig(max_iterations=1, provider_id="openrouter", model_id="model-a"),
    )

    events = [event async for event in agent.run_turn("hello")]
    done = next(event for event in events if isinstance(event, AgentDone))

    assert done.billed_cost == 0.0
    assert done.cost_source != "provider_billed"


@pytest.mark.asyncio
async def test_agent_mixed_breakdown_keeps_exact_rows_without_washing_unverified_cost() -> None:
    provider = _SequenceProvider(
        [
            [
                ProviderText(text="ok"),
                ProviderDone(
                    input_tokens=30,
                    output_tokens=5,
                    billed_cost=0.75,
                    cost_source="mixed",
                    model="ensemble",
                    model_usage_breakdown=[
                        {
                            "provider": "openrouter",
                            "model": "model-exact",
                            "input_tokens": 10,
                            "output_tokens": 2,
                            "billed_cost": 0.25,
                            "cost_source": "provider_billed",
                        },
                        {
                            "provider": "openrouter",
                            "model": "model-unverified",
                            "input_tokens": 20,
                            "output_tokens": 3,
                            "billed_cost": 0.50,
                            "cost_source": "provider_billed_unverified",
                        },
                    ],
                ),
            ]
        ]
    )
    agent = Agent(
        provider=provider,
        config=AgentConfig(max_iterations=1, provider_id="openrouter", model_id="ensemble"),
    )

    events = [event async for event in agent.run_turn("hello")]
    done = next(event for event in events if isinstance(event, AgentDone))
    by_model = {row["model"]: row for row in done.model_usage_breakdown}

    assert done.billed_cost == pytest.approx(0.25)
    assert by_model["model-exact"]["billed_cost"] == pytest.approx(0.25)
    assert by_model["model-unverified"]["billed_cost"] == 0.0
    assert by_model["model-unverified"]["billed_cost_usd"] == 0.0
    assert by_model["model-unverified"]["cost_source"] != "provider_billed"


@pytest.mark.asyncio
async def test_agent_known_error_receipt_is_retained_in_totals_and_llm_error_log() -> None:
    provider = _SequenceProvider(
        [
            [
                ProviderError(
                    message="rate limited after completion",
                    code="429",
                    model_usage_breakdown=[
                        {
                            "provider": "openrouter",
                            "model": "model-a",
                            "input_tokens": 12,
                            "output_tokens": 3,
                            "billed_cost": 0.25,
                            "cost_source": "provider_billed",
                            "provider_usage": {
                                "is_byok": False,
                                "provider_reported_cost": 0.25,
                                "response_ids": ["failed-call-1"],
                                "router_metadata": {"is_byok": False},
                            },
                        }
                    ],
                    usage_missing_count=1,
                )
            ]
        ]
    )
    agent = Agent(
        provider=provider,
        config=AgentConfig(
            max_iterations=1,
            max_provider_retries=0,
            provider_id="openrouter",
            model_id="model-a",
        ),
    )
    call_logs: list[tuple[str, dict[str, Any]]] = []
    agent._write_turn_call_log = (  # type: ignore[method-assign]
        lambda kind, **payload: call_logs.append((kind, payload))
    )

    events = [event async for event in agent.run_turn("hello")]
    done = next(event for event in events if isinstance(event, AgentDone))
    error_log = next(payload for kind, payload in call_logs if kind == "llm_error")

    assert done.input_tokens == 12
    assert done.output_tokens == 3
    assert done.billed_cost == pytest.approx(0.25)
    assert done.model_usage_breakdown[0]["model"] == "model-a"
    assert error_log["usage"]["input_tokens"] == 12
    assert error_log["usage"]["billed_cost"] == pytest.approx(0.25)
    assert error_log["usage"]["model_usage_breakdown"][0]["provider_usage"][
        "response_ids"
    ] == ["failed-call-1"]
    assert error_log["usage_missing_count"] == 1


def test_ensemble_breakdown_is_one_envelope_with_items(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "opensquilla.engine.usage_accounting.resolve_model_price",
        lambda model, provider: ResolvedModelPrice(
            entry=PriceEntry(input_per_m=1.0, output_per_m=2.0),
            source="test",
        ),
    )
    event = ProviderDone(
        input_tokens=30,
        output_tokens=5,
        billed_cost=0.5,
        model_usage_breakdown=[
            {
                "provider": "p1",
                "model": "m1",
                "input_tokens": 10,
                "output_tokens": 2,
                "billed_cost": 0.5,
                "cost_source": "provider_billed",
            },
            {
                "provider": "p2",
                "model": "m2",
                "input_tokens": 20,
                "output_tokens": 3,
                "billed_cost": 0.0,
            },
        ],
    )

    result = normalize_provider_usage(
        event,
        default_provider="ensemble",
        default_model="aggregator",
        completed_at_ms=1234,
    )

    assert len(result.items) == 2
    assert result.billed_cost_nanos == usd_to_nanos("0.5")
    assert result.estimated_cost_nanos == usd_to_nanos("0.000026")
    assert result.cost_source == "mixed"
    assert result.input_tokens == sum(item.input_tokens for item in result.items)
    assert result.output_tokens == sum(item.output_tokens for item in result.items)
    assert result.reasoning_tokens == sum(item.reasoning_tokens for item in result.items)
    assert result.cache_read_tokens == sum(
        item.cache_read_tokens for item in result.items
    )
    assert result.cache_write_tokens == sum(
        item.cache_write_tokens for item in result.items
    )
    assert sum(item.billed_cost_nanos for item in result.items) == result.billed_cost_nanos
    assert (
        sum(item.estimated_cost_nanos for item in result.items)
        == result.estimated_cost_nanos
    )


@pytest.mark.parametrize(
    "untrusted_source",
    ["provider_billed_unverified", "openrouter_byok"],
)
def test_untrusted_provider_cost_never_enters_exact_billed_bucket(
    monkeypatch: pytest.MonkeyPatch,
    untrusted_source: str,
) -> None:
    monkeypatch.setattr(
        "opensquilla.engine.usage_accounting.resolve_model_price",
        lambda model, provider: ResolvedModelPrice(
            entry=PriceEntry(input_per_m=1.0, output_per_m=2.0),
            source="test",
        ),
    )
    result = normalize_provider_usage(
        ProviderDone(
            input_tokens=1_000_000,
            output_tokens=0,
            billed_cost=99.0,
            cost_source=untrusted_source,
            model="model-a",
        ),
        default_provider="openrouter",
        default_model="model-a",
        completed_at_ms=1,
    )

    assert result.billed_cost_nanos == 0
    assert result.estimated_cost_nanos == usd_to_nanos("1.0")
    assert result.cost_source == "opensquilla_estimate"
    assert result.items[0].cost_source == "opensquilla_estimate"


def test_explicit_zero_provider_bill_is_exact_and_not_estimated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "opensquilla.engine.usage_accounting.resolve_model_price",
        lambda model, provider: ResolvedModelPrice(
            entry=PriceEntry(input_per_m=1.0, output_per_m=2.0),
            source="test",
        ),
    )
    result = normalize_provider_usage(
        ProviderDone(
            input_tokens=1_000_000,
            output_tokens=0,
            billed_cost=0.0,
            cost_source="provider_billed",
            model="model-a",
        ),
        default_provider="openrouter",
        default_model="model-a",
        completed_at_ms=1,
    )

    assert result.billed_cost_nanos == 0
    assert result.estimated_cost_nanos == 0
    assert result.cost_source == "provider_billed"
    assert result.items[0].cost_source == "provider_billed"


def test_distinct_unknown_sources_aggregate_to_unavailable_not_mixed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "opensquilla.engine.usage_accounting.resolve_model_price",
        lambda model, provider: ResolvedModelPrice(
            entry=PriceEntry(input_per_m=0.0, output_per_m=0.0),
            source="missing",
        ),
    )
    monkeypatch.setattr(
        "opensquilla.engine.usage_accounting.estimate_cost",
        lambda **kwargs: SimpleNamespace(cost_usd=0.0, basis=None),
    )
    result = normalize_provider_usage(
        ProviderDone(
            input_tokens=3,
            output_tokens=2,
            billed_cost=0.0,
            model_usage_breakdown=[
                {
                    "provider": "openrouter",
                    "model": "model-a",
                    "input_tokens": 1,
                    "output_tokens": 1,
                    "billed_cost": 0.0,
                    "cost_source": "openrouter_byok",
                },
                {
                    "provider": "openrouter",
                    "model": "model-b",
                    "input_tokens": 2,
                    "output_tokens": 1,
                    "billed_cost": 0.0,
                    "cost_source": "provider_billed_unverified",
                },
            ],
        ),
        default_provider="openrouter",
        default_model="ensemble",
        completed_at_ms=1,
    )

    assert result.cost_source == "unavailable"


def test_exact_zero_plus_unknown_aggregates_to_mixed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "opensquilla.engine.usage_accounting.resolve_model_price",
        lambda model, provider: ResolvedModelPrice(
            entry=PriceEntry(input_per_m=0.0, output_per_m=0.0),
            source="missing",
        ),
    )
    monkeypatch.setattr(
        "opensquilla.engine.usage_accounting.estimate_cost",
        lambda **kwargs: SimpleNamespace(cost_usd=0.0, basis=None),
    )
    result = normalize_provider_usage(
        ProviderDone(
            input_tokens=3,
            output_tokens=2,
            billed_cost=0.0,
            model_usage_breakdown=[
                {
                    "provider": "openrouter",
                    "model": "model-a",
                    "input_tokens": 1,
                    "output_tokens": 1,
                    "billed_cost": 0.0,
                    "cost_source": "provider_billed",
                },
                {
                    "provider": "openrouter",
                    "model": "model-b",
                    "input_tokens": 2,
                    "output_tokens": 1,
                    "billed_cost": 0.0,
                    "cost_source": "provider_billed_unverified",
                },
            ],
        ),
        default_provider="openrouter",
        default_model="ensemble",
        completed_at_ms=1,
    )

    assert result.cost_source == "mixed"


def test_incomplete_breakdown_falls_back_to_done_envelope() -> None:
    event = ProviderDone(
        input_tokens=30,
        output_tokens=5,
        cached_tokens=4,
        billed_cost=0.75,
        cost_source="provider_billed",
        model="aggregate-model",
        model_usage_breakdown=[
            {
                "provider": "p1",
                "model": "m1",
                "input_tokens": 10,
                "output_tokens": 2,
                "billed_cost": 0.25,
                "cost_source": "provider_billed",
            }
        ],
    )

    result = normalize_provider_usage(
        event,
        default_provider="ensemble",
        default_model="aggregate-model",
        completed_at_ms=1234,
    )

    assert len(result.items) == 1
    assert result.input_tokens == 30
    assert result.output_tokens == 5
    assert result.cache_read_tokens == 4
    assert result.billed_cost_nanos == usd_to_nanos("0.75")
    assert result.items[0].model == "aggregate-model"


def test_partial_ensemble_error_preserves_known_items_and_missing_coverage() -> None:
    event = ProviderError(
        message="aggregator failed",
        code="ensemble_aggregator_error",
        model_usage_breakdown=[
            {
                "provider": "p1",
                "model": "m1",
                "input_tokens": 10,
                "output_tokens": 2,
                "billed_cost": 0.25,
                "cost_source": "provider_billed",
            }
        ],
        usage_missing_count=1,
    )

    result = normalize_provider_usage(
        event,
        default_provider="ensemble",
        default_model="aggregator",
        completed_at_ms=1234,
    )

    assert len(result.items) == 1
    assert result.items[0].model == "m1"
    assert result.billed_cost_nanos == usd_to_nanos("0.25")
    assert result.missing_usage_entries == 1


def test_complete_ensemble_error_preserves_known_items_without_missing_coverage() -> None:
    event = ProviderError(
        message="aggregator was unavailable",
        code="ensemble_aggregator_error",
        model_usage_breakdown=[
            {
                "provider": "p1",
                "model": "m1",
                "input_tokens": 10,
                "output_tokens": 2,
                "billed_cost": 0.25,
                "cost_source": "provider_billed",
            }
        ],
        usage_missing_count=0,
    )

    result = normalize_provider_usage(
        event,
        default_provider="ensemble",
        default_model="aggregator",
        completed_at_ms=1234,
    )

    assert len(result.items) == 1
    assert result.items[0].model == "m1"
    assert result.billed_cost_nanos == usd_to_nanos("0.25")
    assert result.missing_usage_entries == 0


@pytest.mark.asyncio
async def test_partial_ensemble_error_finalizes_outer_call_instead_of_unknown() -> None:
    sink = _RecordingSink()
    scope = UsageAccountingScope(sink=sink, context=_context())

    async def stream() -> AsyncIterator[ProviderError]:
        yield ProviderError(
            message="fallback failed",
            code="ensemble_fallback_incomplete",
            model_usage_breakdown=[
                {
                    "provider": "p1",
                    "model": "m1",
                    "input_tokens": 4,
                    "output_tokens": 2,
                    "billed_cost": 0.1,
                    "cost_source": "provider_billed",
                }
            ],
            usage_missing_count=2,
        )

    with bind_usage_accounting_scope(scope):
        events = [
            event
            async for event in account_provider_stream(
                stream,
                provider="ensemble",
                model="aggregator",
            )
        ]

    assert len(events) == 1
    assert len(sink.finalized) == 1
    assert sink.finalized[0][1].missing_usage_entries == 2
    assert sink.unknown == []


@pytest.mark.asyncio
async def test_complete_ensemble_error_finalizes_outer_call_instead_of_unknown() -> None:
    sink = _RecordingSink()
    scope = UsageAccountingScope(sink=sink, context=_context())

    async def stream() -> AsyncIterator[ProviderError]:
        yield ProviderError(
            message="aggregator was unavailable",
            code="ensemble_aggregator_error",
            model_usage_breakdown=[
                {
                    "provider": "p1",
                    "model": "m1",
                    "input_tokens": 4,
                    "output_tokens": 2,
                    "billed_cost": 0.1,
                    "cost_source": "provider_billed",
                }
            ],
            usage_missing_count=0,
        )

    with bind_usage_accounting_scope(scope):
        events = [
            event
            async for event in account_provider_stream(
                stream,
                provider="ensemble",
                model="aggregator",
            )
        ]

    assert len(events) == 1
    assert len(sink.finalized) == 1
    assert sink.finalized[0][1].missing_usage_entries == 0
    assert sink.unknown == []


@pytest.mark.asyncio
async def test_agent_finalizes_partial_error_with_a_known_receipt() -> None:
    sink = _RecordingSink()
    provider = _SequenceProvider(
        [
            [
                ProviderError(
                    message="aggregator failed",
                    code="ensemble_aggregator_error",
                    model_usage_breakdown=[
                        {
                            "provider": "p1",
                            "model": "m1",
                            "input_tokens": 4,
                            "output_tokens": 2,
                            "billed_cost": 0.1,
                            "cost_source": "provider_billed",
                        }
                    ],
                    usage_missing_count=1,
                )
            ]
        ]
    )
    agent = Agent(
        provider=provider,
        config=AgentConfig(max_iterations=1, max_provider_retries=0),
        usage_event_sink=sink,
        usage_execution_context=_context(),
    )

    async for _ in agent.run_turn("hello"):
        pass

    assert len(sink.finalized) == 1
    assert sink.finalized[0][1].missing_usage_entries == 1
    assert sink.unknown == []


@pytest.mark.asyncio
async def test_partial_error_missing_count_without_known_rows_remains_unknown() -> None:
    sink = _RecordingSink()
    scope = UsageAccountingScope(sink=sink, context=_context())

    async def stream() -> AsyncIterator[ProviderError]:
        yield ProviderError(
            message="fallback failed before a receipt",
            code="ensemble_fallback_incomplete",
            model_usage_breakdown=[],
            usage_missing_count=2,
        )

    with bind_usage_accounting_scope(scope):
        events = [
            event
            async for event in account_provider_stream(
                stream,
                provider="ensemble",
                model="aggregator",
            )
        ]

    assert len(events) == 1
    assert sink.finalized == []
    assert [reason for _, reason in sink.unknown] == [
        "provider_error:incomplete_stream"
    ]


def test_runtime_subagent_inherits_sink_with_distinct_execution() -> None:
    sink = _RecordingSink()
    parent = Agent(
        provider=_ErrorProvider(),
        config=AgentConfig(),
        usage_event_sink=sink,
        usage_execution_context=_context(),
    )

    child = parent._make_child_agent(SubagentSpec(task="child"), depth=1)

    assert child._usage_event_sink is sink
    child_context = child._usage_execution_context
    assert child_context is not None
    assert child_context.execution_id != "turn-1"
    assert child_context.parent_turn_id == "turn-1"
    assert child_context.session_id == "session-1"
    assert child_context.session_epoch == 7
    assert child_context.run_kind == "subagent"


@pytest.mark.asyncio
async def test_direct_meta_llm_helper_records_usage_with_parent_attribution() -> None:
    sink = _RecordingSink()
    provider = _DoneProvider(sink)
    chat = make_llm_chat_from_provider(
        provider=provider,
        base_config=AgentConfig(provider_id="fake", model_id="model-a"),
        usage_event_sink=sink,
        usage_execution_context=_context(),
    )

    result = await chat("system", "user")

    assert result == "ok"
    assert len(sink.started) == 1
    call = sink.started[0]
    assert call.execution_id != "turn-1"
    assert call.parent_turn_id == "turn-1"
    assert call.session_id == "session-1"
    assert call.session_epoch == 7
    assert call.run_kind == "meta_llm"
    assert len(sink.finalized) == 1
    assert sink.unknown == []


@pytest.mark.asyncio
async def test_selector_fallback_accounts_each_physical_leg_without_outer_duplicate() -> None:
    sink = _RecordingSink()
    fallback = _PhysicalLegProvider(
        "anthropic",
        [
            ProviderText(text="fallback"),
            ProviderDone(
                input_tokens=7,
                output_tokens=2,
                billed_cost=0.25,
                cost_source="provider_billed",
                model="fallback-model",
            ),
        ],
    )
    primary = _PhysicalLegProvider(
        "openai",
        [ProviderError(message="rate limited", code="429")],
    )
    wrapper = _SelectorFallbackProvider(primary, _FallbackSelector(fallback))
    tracker = _RecordingTracker()
    agent = Agent(
        provider=wrapper,
        config=AgentConfig(
            max_iterations=1,
            max_provider_retries=0,
            provider_id="openai",
            model_id="primary-model",
        ),
        usage_tracker=tracker,
        session_key="agent:main:test",
        usage_event_sink=sink,
        usage_execution_context=_context(),
    )

    async for _ in agent.run_turn("hello"):
        pass

    assert primary.calls == 1
    assert fallback.calls == 1
    assert [(call.call_index, call.provider, call.model) for call in sink.started] == [
        (1, "openai", "primary-model"),
        (2, "anthropic", "fallback-model"),
    ]
    assert [(call.call_index, reason) for call, reason in sink.unknown] == [
        (1, "provider_error:429")
    ]
    assert [call.call_index for call, _ in sink.finalized] == [2]
    assert len(sink.started) == 2  # no Agent-level wrapper envelope
    assert tracker.rows[0][1]["provider"] == "anthropic"
    assert tracker.rows[0][1]["model_id"] == "fallback-model"


@pytest.mark.asyncio
async def test_selector_wrapper_without_ledger_scope_is_streaming_compatible() -> None:
    fallback = _PhysicalLegProvider(
        "anthropic",
        [ProviderText(text="ok"), ProviderDone(model="fallback-model")],
    )
    primary = _PhysicalLegProvider(
        "openai",
        [ProviderError(message="rate limited", code="429")],
    )
    wrapper = _SelectorFallbackProvider(primary, _FallbackSelector(fallback))

    events = [event async for event in wrapper.chat([])]

    assert [getattr(event, "kind", "") for event in events] == ["text_delta", "done"]
    assert primary.calls == fallback.calls == 1


@pytest.mark.asyncio
async def test_meta_helper_with_selector_records_only_physical_legs() -> None:
    sink = _RecordingSink()
    fallback = _PhysicalLegProvider(
        "anthropic",
        [ProviderText(text="ok"), ProviderDone(model="fallback-model")],
    )
    primary = _PhysicalLegProvider(
        "openai",
        [ProviderError(message="rate limited", code="429")],
    )
    wrapper = _SelectorFallbackProvider(primary, _FallbackSelector(fallback))
    chat = make_llm_chat_from_provider(
        provider=wrapper,
        base_config=AgentConfig(provider_id="openai", model_id="primary-model"),
        usage_event_sink=sink,
        usage_execution_context=_context(),
    )

    assert await chat("system", "user") == "ok"

    assert [(call.call_index, call.provider, call.model) for call in sink.started] == [
        (1, "openai", "primary-model"),
        (2, "anthropic", "fallback-model"),
    ]
    assert {call.execution_id for call in sink.started} != {"turn-1"}
    assert all(call.run_kind == "meta_llm" for call in sink.started)
    assert len(sink.finalized) == 1
    assert len(sink.unknown) == 1


@pytest.mark.asyncio
async def test_shared_turn_scope_keeps_helper_and_agent_call_indices_unique() -> None:
    sink = _RecordingSink()
    context = _context()
    scope = UsageAccountingScope(sink=sink, context=context)
    helper_provider = _SequenceProvider([[ProviderDone(model="gate-model")]])
    agent_provider = _SequenceProvider(
        [[ProviderText(text="ok"), ProviderDone(model="agent-model")]]
    )
    agent = Agent(
        provider=agent_provider,
        config=AgentConfig(max_iterations=1, model_id="agent-model"),
        usage_event_sink=sink,
        usage_execution_context=context,
    )

    with bind_usage_accounting_scope(scope):
        _ = [
            event
            async for event in account_provider_stream(
                lambda: helper_provider.chat([]),
                provider="gate-provider",
                model="gate-model",
            )
        ]
        async for _ in agent.run_turn("hello"):
            pass

    assert [call.call_index for call in sink.started] == [1, 2]
    assert len({call.event_id for call in sink.started}) == 2


@pytest.mark.asyncio
async def test_turn_runner_preserves_retryable_ledger_start_error_code() -> None:
    storage = SessionStorage(":memory:")
    await storage.connect()
    manager = SessionManager(storage)
    session_key = "agent:main:usage-start-failure"
    await manager.create(session_key)
    sink = _UnavailableSink()
    provider = _SequenceProvider([[ProviderDone()]])
    runner = TurnRunner(
        provider_selector=_SingleProviderSelector(provider),
        session_manager=manager,
        usage_event_sink=sink,
    )
    try:
        events = [
            event
            async for event in runner.run(
                "hello",
                session_key,
                tool_context=ToolContext(
                    session_key=session_key,
                    caller_kind=CallerKind.CLI,
                ),
                history_has_persisted_user=False,
                no_memory_capture=True,
            )
        ]
    finally:
        await storage.close()

    errors = [event for event in events if isinstance(event, ErrorEvent)]
    assert len(errors) == 1
    assert errors[0].code == UsageAccountingUnavailableError.code
    assert provider.calls == 0
