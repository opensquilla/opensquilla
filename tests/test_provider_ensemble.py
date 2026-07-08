from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import pytest

from opensquilla.provider import (
    ChatConfig,
    DoneEvent,
    ErrorEvent,
    Message,
    ProviderHeartbeatEvent,
    TextDeltaEvent,
    ToolDefinition,
    ToolInputSchema,
)
from opensquilla.provider.ensemble import EnsembleMemberConfig, EnsembleProvider
from opensquilla.provider.selector import ProviderConfig
from opensquilla.provider.types import EnsembleProgressEvent, StreamEvent


@dataclass
class _FakePlan:
    events: list[StreamEvent]
    delay: float = 0.0
    gate: asyncio.Event | None = None


@dataclass
class _FakeRegistry:
    plans: dict[str, _FakePlan]
    calls: list[dict[str, Any]] = field(default_factory=list)

    def provider_for(self, cfg: ProviderConfig) -> _FakeProvider:
        return _FakeProvider(cfg, self)


class _FakeProvider:
    provider_name = "fake"

    def __init__(self, cfg: ProviderConfig, registry: _FakeRegistry) -> None:
        self._cfg = cfg
        self._registry = registry

    def chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        config: ChatConfig | None = None,
    ) -> AsyncIterator[StreamEvent]:
        return self._chat(messages, tools=tools, config=config)

    async def _chat(
        self,
        messages: list[Message],
        *,
        tools: list[ToolDefinition] | None,
        config: ChatConfig | None,
    ) -> AsyncIterator[StreamEvent]:
        self._registry.calls.append(
            {
                "model": self._cfg.model,
                "messages": messages,
                "tools": tools,
                "config": config,
                "started_at": time.monotonic(),
            }
        )
        plan = self._registry.plans[self._cfg.model]
        if plan.delay > 0:
            await asyncio.sleep(plan.delay)
        if plan.gate is not None:
            await plan.gate.wait()
        for event in plan.events:
            yield event

    async def list_models(self) -> list[Any]:
        return []


def _member(model: str, *, thinking: str | None = "high") -> EnsembleMemberConfig:
    return EnsembleMemberConfig(
        provider_config=ProviderConfig(provider="fake", model=model),
        label=model,
        thinking=thinking,
    )


def _openrouter_member(model: str, *, thinking: str | None = "high") -> EnsembleMemberConfig:
    return EnsembleMemberConfig(
        provider_config=ProviderConfig(
            provider="openrouter",
            model=model,
            base_url="https://openrouter.ai/api/v1",
        ),
        label=model,
        thinking=thinking,
    )


@pytest.mark.asyncio
async def test_ensemble_emits_heartbeat_while_waiting_for_slow_proposers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = _FakeRegistry(
        {
            "p1": _FakePlan(
                [TextDeltaEvent(text="draft"), DoneEvent(model="p1")],
                delay=0.05,
            ),
            "agg": _FakePlan([TextDeltaEvent(text="final"), DoneEvent(model="agg")]),
        }
    )
    monkeypatch.setattr("opensquilla.provider.ensemble._build_provider", registry.provider_for)
    monkeypatch.setattr(
        "opensquilla.provider.ensemble._ENSEMBLE_HEARTBEAT_INTERVAL_SECONDS",
        0.01,
        raising=False,
    )
    provider = EnsembleProvider(
        profile_name="default",
        proposers=[_member("p1")],
        aggregator=_member("agg"),
        proposer_timeout_seconds=1,
        aggregator_timeout_seconds=1,
        shuffle_candidates=False,
    )

    events = await _collect(provider)

    assert any(
        isinstance(event, ProviderHeartbeatEvent)
        and event.phase == "ensemble_proposers_wait"
        for event in events
    )


@pytest.mark.asyncio
async def test_ensemble_emits_heartbeat_while_waiting_for_slow_aggregator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = _FakeRegistry(
        {
            "p1": _FakePlan([TextDeltaEvent(text="draft"), DoneEvent(model="p1")]),
            "agg": _FakePlan(
                [TextDeltaEvent(text="final"), DoneEvent(model="agg")],
                delay=0.05,
            ),
        }
    )
    monkeypatch.setattr("opensquilla.provider.ensemble._build_provider", registry.provider_for)
    monkeypatch.setattr(
        "opensquilla.provider.ensemble._ENSEMBLE_HEARTBEAT_INTERVAL_SECONDS",
        0.01,
        raising=False,
    )
    provider = EnsembleProvider(
        profile_name="default",
        proposers=[_member("p1")],
        aggregator=_member("agg"),
        proposer_timeout_seconds=1,
        aggregator_timeout_seconds=1,
        shuffle_candidates=False,
    )

    events = await _collect(provider)

    assert any(
        isinstance(event, ProviderHeartbeatEvent)
        and event.phase == "ensemble_aggregator_wait"
        for event in events
    )


def _tool() -> ToolDefinition:
    return ToolDefinition(
        name="lookup",
        description="Lookup test data",
        input_schema=ToolInputSchema(),
    )


async def _collect(provider: EnsembleProvider) -> list[StreamEvent]:
    return [
        event
        async for event in provider.chat(
            [Message(role="user", content="answer this")],
            tools=[_tool()],
            config=ChatConfig(max_tokens=99, thinking=False),
        )
    ]


@pytest.mark.asyncio
async def test_ensemble_runs_proposers_concurrently_and_tools_only_reach_aggregator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = _FakeRegistry(
        {
            "p1": _FakePlan(
                [
                    TextDeltaEvent(text="draft one"),
                    DoneEvent(input_tokens=1, output_tokens=2, model="p1"),
                ],
                delay=0.1,
            ),
            "p2": _FakePlan(
                [
                    TextDeltaEvent(text="draft two"),
                    DoneEvent(input_tokens=3, output_tokens=4, model="p2"),
                ],
                delay=0.1,
            ),
            "agg": _FakePlan(
                [
                    TextDeltaEvent(text="final"),
                    DoneEvent(
                        input_tokens=5,
                        output_tokens=6,
                        billed_cost=0.25,
                        model="agg",
                        cost_source="provider_billed",
                    ),
                ]
            ),
        }
    )
    monkeypatch.setattr("opensquilla.provider.ensemble._build_provider", registry.provider_for)
    provider = EnsembleProvider(
        profile_name="default",
        proposers=[_member("p1"), _member("p2")],
        aggregator=_member("agg"),
        proposer_timeout_seconds=1,
        aggregator_timeout_seconds=1,
        shuffle_candidates=False,
    )

    started = time.monotonic()
    events = await _collect(provider)
    elapsed = time.monotonic() - started

    assert elapsed < 0.18
    assert [call["model"] for call in registry.calls] == ["p1", "p2", "agg"]
    assert abs(registry.calls[0]["started_at"] - registry.calls[1]["started_at"]) < 0.05
    assert registry.calls[0]["tools"] is None
    assert registry.calls[1]["tools"] is None
    assert registry.calls[2]["tools"] is not None
    assert "draft one" in str(registry.calls[2]["messages"][-1].content)
    assert "draft two" in str(registry.calls[2]["messages"][-1].content)

    assert any(isinstance(event, TextDeltaEvent) and event.text == "final" for event in events)
    done = next(event for event in events if isinstance(event, DoneEvent))
    assert done.input_tokens == 9
    assert done.output_tokens == 12
    assert done.billed_cost == 0.25
    assert done.model == "agg"
    assert done.model_usage_breakdown == [
        {
            "role": "proposer",
            "profile": "default",
            "label": "p1",
            "provider": "fake",
            "model": "p1",
            "sample_index": 0,
            "input_tokens": 1,
            "output_tokens": 2,
            "reasoning_tokens": 0,
            "cached_tokens": 0,
            "cache_write_tokens": 0,
            "billed_cost": 0.0,
            "cost_source": "none",
        },
        {
            "role": "proposer",
            "profile": "default",
            "label": "p2",
            "provider": "fake",
            "model": "p2",
            "sample_index": 0,
            "input_tokens": 3,
            "output_tokens": 4,
            "reasoning_tokens": 0,
            "cached_tokens": 0,
            "cache_write_tokens": 0,
            "billed_cost": 0.0,
            "cost_source": "none",
        },
        {
            "role": "aggregator",
            "profile": "default",
            "label": "aggregator",
            "provider": "fake",
            "model": "agg",
            "sample_index": 0,
            "input_tokens": 5,
            "output_tokens": 6,
            "reasoning_tokens": 0,
            "cached_tokens": 0,
            "cache_write_tokens": 0,
            "billed_cost": 0.25,
            "cost_source": "provider_billed",
        },
    ]
    assert done.ensemble_trace is not None
    assert done.ensemble_trace["profile"] == "default"
    assert done.ensemble_trace["successful_proposers"] == 2
    assert done.ensemble_trace["fallback_used"] is False
    assert done.ensemble_trace["llm_request_count"] == 3
    assert done.ensemble_trace["content_max_chars"] == 8000
    first_candidate = done.ensemble_trace["candidates"][0]
    assert first_candidate["execution"]["role"] == "proposer"
    assert first_candidate["execution"]["model"] == "p1"
    assert first_candidate["execution"]["thinking_override"] == "high"
    assert first_candidate["execution"]["tools_enabled"] is False
    assert first_candidate["execution"]["effective_max_tokens"] == 16384
    assert first_candidate["content"]["text"] == "draft one"
    assert first_candidate["content"]["truncated"] is False
    final_request = done.ensemble_trace["final_request"]
    assert final_request["role"] == "aggregator"
    assert final_request["execution"]["model"] == "agg"
    assert final_request["execution"]["tools_enabled"] is True
    assert final_request["execution"]["tool_names"] == ["lookup"]
    assert final_request["execution"]["effective_max_tokens"] == 16384
    assert "draft one" in final_request["input"]["messages"][-1]["content"]["text"]
    assert final_request["output"]["text"] == "final"
    assert final_request["usage"]["model"] == "agg"
    json.dumps(done.ensemble_trace)


@pytest.mark.asyncio
async def test_ensemble_resolves_max_tokens_per_openrouter_member(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    models = [
        "deepseek/deepseek-v4-pro",
        "z-ai/glm-5.2",
        "moonshotai/kimi-k2.7-code",
        "qwen/qwen3.7-max",
    ]
    registry = _FakeRegistry(
        {
            **{
                model: _FakePlan(
                    [
                        TextDeltaEvent(text=f"draft from {model}"),
                        DoneEvent(input_tokens=1, output_tokens=1, model=model),
                    ]
                )
                for model in models
            },
            "agg": _FakePlan(
                [
                    TextDeltaEvent(text="final"),
                    DoneEvent(input_tokens=1, output_tokens=1, model="agg"),
                ]
            ),
        }
    )
    monkeypatch.setattr("opensquilla.provider.ensemble._build_provider", registry.provider_for)
    provider = EnsembleProvider(
        profile_name="static_openrouter_b5",
        proposers=[_openrouter_member(model, thinking=None) for model in models],
        aggregator=EnsembleMemberConfig(
            provider_config=ProviderConfig(
                provider="openrouter",
                model="agg",
                base_url="https://openrouter.ai/api/v1",
            ),
            label="aggregator",
            max_tokens=123,
            thinking=None,
        ),
        proposer_timeout_seconds=1,
        aggregator_timeout_seconds=1,
        shuffle_candidates=False,
    )

    events = [
        event
        async for event in provider.chat(
            [Message(role="user", content="answer this")],
            config=ChatConfig(max_tokens=384000, thinking=False),
        )
    ]

    by_model = {call["model"]: call["config"].max_tokens for call in registry.calls}
    assert by_model == {
        "deepseek/deepseek-v4-pro": 384000,
        # models.dev's 2026-07-08 refresh lowered openrouter z-ai/glm-5.2 max
        # output from 131072 to 32768.
        "z-ai/glm-5.2": 32768,
        "moonshotai/kimi-k2.7-code": 16384,
        "qwen/qwen3.7-max": 65536,
        "agg": 123,
    }
    done = next(event for event in events if isinstance(event, DoneEvent))
    assert done.ensemble_trace is not None
    traced = {
        candidate["execution"]["model"]: candidate["execution"]["effective_max_tokens"]
        for candidate in done.ensemble_trace["candidates"]
    }
    assert traced["moonshotai/kimi-k2.7-code"] == 16384
    assert done.ensemble_trace["final_request"]["execution"]["effective_max_tokens"] == 123


@pytest.mark.asyncio
async def test_ensemble_uses_fallback_when_too_few_proposers_succeed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = _FakeRegistry(
        {
            "p1": _FakePlan(
                [
                    TextDeltaEvent(text="draft one"),
                    DoneEvent(input_tokens=1, output_tokens=2, model="p1"),
                ]
            ),
            "p2": _FakePlan([ErrorEvent(message="nope", code="boom")]),
        }
    )
    monkeypatch.setattr("opensquilla.provider.ensemble._build_provider", registry.provider_for)

    class _FallbackProvider:
        provider_name = "fallback"

        def chat(
            self,
            messages: list[Message],
            tools: list[ToolDefinition] | None = None,
            config: ChatConfig | None = None,
        ) -> AsyncIterator[StreamEvent]:
            async def _stream() -> AsyncIterator[StreamEvent]:
                yield TextDeltaEvent(text="single")
                yield DoneEvent(input_tokens=7, output_tokens=8, model="single")

            return _stream()

        async def list_models(self) -> list[Any]:
            return []

    provider = EnsembleProvider(
        profile_name="default",
        proposers=[_member("p1"), _member("p2")],
        aggregator=_member("agg"),
        fallback_provider=_FallbackProvider(),
        min_successful_proposers=2,
        proposer_timeout_seconds=1,
        aggregator_timeout_seconds=1,
        shuffle_candidates=False,
    )

    events = await _collect(provider)

    assert [call["model"] for call in registry.calls] == ["p1", "p2"]
    assert any(isinstance(event, TextDeltaEvent) and event.text == "single" for event in events)
    done = next(event for event in events if isinstance(event, DoneEvent))
    assert done.input_tokens == 8
    assert done.output_tokens == 10
    assert done.model_usage_breakdown[-1]["role"] == "fallback_single"
    assert done.ensemble_trace is not None
    assert done.ensemble_trace["fallback_used"] is True
    assert "requires 2" in done.ensemble_trace["fallback_reason"]
    assert done.ensemble_trace["final_request"]["role"] == "fallback_single"
    assert done.ensemble_trace["final_request"]["output"]["text"] == "single"
    assert done.ensemble_trace["final_request"]["usage"]["model"] == "single"


@pytest.mark.asyncio
async def test_openrouter_members_get_member_specific_reasoning_capabilities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = _FakeRegistry(
        {
            "z-ai/glm-5.2": _FakePlan(
                [TextDeltaEvent(text="draft"), DoneEvent(model="z-ai/glm-5.2")]
            ),
            "qwen/qwen3.7-plus": _FakePlan(
                [TextDeltaEvent(text="final"), DoneEvent(model="qwen/qwen3.7-plus")]
            ),
        }
    )
    monkeypatch.setattr("opensquilla.provider.ensemble._build_provider", registry.provider_for)
    provider = EnsembleProvider(
        profile_name="default",
        proposers=[_openrouter_member("z-ai/glm-5.2")],
        aggregator=_openrouter_member("qwen/qwen3.7-plus"),
        proposer_timeout_seconds=1,
        aggregator_timeout_seconds=1,
        shuffle_candidates=False,
    )

    await _collect(provider)

    proposer_cfg = registry.calls[0]["config"]
    aggregator_cfg = registry.calls[1]["config"]
    assert proposer_cfg.thinking is True
    assert proposer_cfg.thinking_level == "high"
    assert proposer_cfg.model_capabilities.supports_reasoning is True
    assert proposer_cfg.model_capabilities.reasoning_format == "openrouter"
    assert aggregator_cfg.thinking is True
    assert aggregator_cfg.thinking_level == "high"
    assert aggregator_cfg.model_capabilities.supports_reasoning is True
    assert aggregator_cfg.model_capabilities.reasoning_format == "openrouter"


@pytest.mark.asyncio
async def test_ensemble_emits_proposer_progress_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = _FakeRegistry(
        {
            "p1": _FakePlan(
                [TextDeltaEvent(text="d1"), DoneEvent(input_tokens=1, output_tokens=2, model="p1")]
            ),
            "p2": _FakePlan(
                [TextDeltaEvent(text="d2"), DoneEvent(input_tokens=3, output_tokens=4, model="p2")]
            ),
            "agg": _FakePlan(
                [TextDeltaEvent(text="f"), DoneEvent(input_tokens=5, output_tokens=6, model="agg")]
            ),
        }
    )
    monkeypatch.setattr("opensquilla.provider.ensemble._build_provider", registry.provider_for)
    provider = EnsembleProvider(
        profile_name="default",
        proposers=[_member("p1"), _member("p2")],
        aggregator=_member("agg"),
        proposer_timeout_seconds=1,
        aggregator_timeout_seconds=1,
        shuffle_candidates=False,
    )

    events = await _collect(provider)
    progress = [event for event in events if isinstance(event, EnsembleProgressEvent)]

    # Each proposer announces a start and a finish so the UI can reveal it live.
    starts = {p.proposer_model for p in progress if p.event_type == "proposer_start"}
    finishes = {p.proposer_model for p in progress if p.event_type == "proposer_finish"}
    assert starts == {"p1", "p2"}
    assert finishes == {"p1", "p2"}

    # The finish delta carries the proposer's usage/cost so the UI can render
    # per-member tokens live (not just at the terminal breakdown).
    p1_finish = next(
        p
        for p in progress
        if p.event_type == "proposer_finish" and p.proposer_model == "p1"
    )
    assert p1_finish.input_tokens == 1
    assert p1_finish.output_tokens == 2

    # Progress is delivered before the terminal DoneEvent that carries the breakdown.
    last_progress = max(i for i, e in enumerate(events) if isinstance(e, EnsembleProgressEvent))
    done_index = max(i for i, e in enumerate(events) if isinstance(e, DoneEvent))
    assert last_progress < done_index


@pytest.mark.asyncio
async def test_ensemble_streams_proposer_progress_live_not_buffered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # p2 blocks until `gate` is set. The consumer sets the gate only AFTER it has
    # received p1's proposer_finish from the LIVE stream. If progress were buffered
    # until gather() completed, p1's finish would never surface (p2 stays blocked,
    # gather never returns) → deadlock. Live streaming completes within the timeout.
    gate = asyncio.Event()
    registry = _FakeRegistry(
        {
            "p1": _FakePlan([DoneEvent(input_tokens=1, output_tokens=1, model="p1")]),
            "p2": _FakePlan([DoneEvent(input_tokens=1, output_tokens=1, model="p2")], gate=gate),
            "agg": _FakePlan(
                [TextDeltaEvent(text="f"), DoneEvent(input_tokens=1, output_tokens=1, model="agg")]
            ),
        }
    )
    monkeypatch.setattr("opensquilla.provider.ensemble._build_provider", registry.provider_for)
    provider = EnsembleProvider(
        profile_name="default",
        proposers=[_member("p1"), _member("p2")],
        aggregator=_member("agg"),
        proposer_timeout_seconds=2,
        aggregator_timeout_seconds=2,
        shuffle_candidates=False,
    )

    async def consume() -> list[StreamEvent]:
        collected: list[StreamEvent] = []
        async for event in provider.chat(
            [Message(role="user", content="q")],
            config=ChatConfig(max_tokens=8, thinking=False),
        ):
            collected.append(event)
            if (
                isinstance(event, EnsembleProgressEvent)
                and event.event_type == "proposer_finish"
                and event.proposer_model == "p1"
            ):
                gate.set()  # reachable only if p1's finish streamed live
        return collected

    events = await asyncio.wait_for(consume(), timeout=3.0)
    finishes = {
        e.proposer_model
        for e in events
        if isinstance(e, EnsembleProgressEvent) and e.event_type == "proposer_finish"
    }
    assert finishes == {"p1", "p2"}


@pytest.mark.asyncio
async def test_static_openrouter_b5_quorum_cancels_slow_proposer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slow_gate = asyncio.Event()
    registry = _FakeRegistry(
        {
            "p1": _FakePlan([TextDeltaEvent(text="d1"), DoneEvent(model="p1")]),
            "p2": _FakePlan([TextDeltaEvent(text="d2"), DoneEvent(model="p2")]),
            "p3": _FakePlan([TextDeltaEvent(text="d3"), DoneEvent(model="p3")]),
            "p4": _FakePlan(
                [TextDeltaEvent(text="d4"), DoneEvent(model="p4")],
                gate=slow_gate,
            ),
            "agg": _FakePlan(
                [
                    TextDeltaEvent(text="final"),
                    DoneEvent(input_tokens=1, output_tokens=1, model="agg"),
                ]
            ),
        }
    )
    monkeypatch.setattr("opensquilla.provider.ensemble._build_provider", registry.provider_for)
    provider = EnsembleProvider(
        profile_name="static_openrouter_b5",
        proposers=[_member("p1"), _member("p2"), _member("p3"), _member("p4")],
        aggregator=_member("agg"),
        min_successful_proposers=3,
        proposer_timeout_seconds=10,
        aggregator_timeout_seconds=1,
        quorum_grace_seconds=0.02,
        shuffle_candidates=False,
    )

    started = time.monotonic()
    events = await _collect(provider)
    elapsed = time.monotonic() - started

    assert elapsed < 0.5
    assert [call["model"] for call in registry.calls] == ["p1", "p2", "p3", "p4", "agg"]
    done = next(event for event in events if isinstance(event, DoneEvent))
    assert done.ensemble_trace is not None
    assert done.ensemble_trace["successful_proposers"] == 3
    assert done.ensemble_trace["selected_candidate_count"] == 3
    assert done.ensemble_trace["selected_candidate_indexes"] == [0, 1, 2]
    assert done.ensemble_trace["llm_request_count"] == 5
    assert done.ensemble_trace["quorum_grace_seconds"] == 0.02
    p4 = done.ensemble_trace["candidates"][3]
    assert p4["model"] == "p4"
    assert p4["ok"] is False
    assert p4["error_code"] == "quorum_cancelled"
    assert "quorum grace" in p4["error"]
    assert "d1" in str(registry.calls[-1]["messages"][-1].content)
    assert "d2" in str(registry.calls[-1]["messages"][-1].content)
    assert "d3" in str(registry.calls[-1]["messages"][-1].content)
    assert "d4" not in str(registry.calls[-1]["messages"][-1].content)


@pytest.mark.asyncio
async def test_default_ensemble_waits_for_all_proposers_without_quorum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slow_gate = asyncio.Event()
    registry = _FakeRegistry(
        {
            "p1": _FakePlan([TextDeltaEvent(text="d1"), DoneEvent(model="p1")]),
            "p2": _FakePlan(
                [TextDeltaEvent(text="d2"), DoneEvent(model="p2")],
                gate=slow_gate,
            ),
            "agg": _FakePlan([TextDeltaEvent(text="final"), DoneEvent(model="agg")]),
        }
    )
    monkeypatch.setattr("opensquilla.provider.ensemble._build_provider", registry.provider_for)
    provider = EnsembleProvider(
        profile_name="router_dynamic/c1",
        proposers=[_member("p1"), _member("p2")],
        aggregator=_member("agg"),
        min_successful_proposers=1,
        proposer_timeout_seconds=2,
        aggregator_timeout_seconds=1,
        quorum_grace_seconds=0.0,
        shuffle_candidates=False,
    )

    consume_task = asyncio.create_task(_collect(provider))
    await asyncio.sleep(0.05)
    assert "agg" not in [call["model"] for call in registry.calls]

    slow_gate.set()
    events = await asyncio.wait_for(consume_task, timeout=1.0)

    assert [call["model"] for call in registry.calls] == ["p1", "p2", "agg"]
    done = next(event for event in events if isinstance(event, DoneEvent))
    assert done.ensemble_trace is not None
    assert done.ensemble_trace["successful_proposers"] == 2
    assert done.ensemble_trace["quorum_grace_seconds"] == 0.0


def test_runtime_wrap_is_after_selector_resolution() -> None:
    import inspect

    from opensquilla.engine.runtime import TurnRunner

    source = inspect.getsource(TurnRunner._run_pipeline)
    resolve_index = source.index("provider = apply_model_override(")
    wrap_index = source.index("build_ensemble_provider_from_config")

    assert wrap_index > resolve_index
    assert "routed_model_before_ensemble" in source
    assert "current_provider_config" in source


@pytest.mark.asyncio
async def test_runtime_normalizes_provider_ensemble_progress_event() -> None:
    from opensquilla.engine.runtime import _SelectorFallbackProvider
    from opensquilla.engine.types import EnsembleProgressEvent as EngineEnsembleProgressEvent

    class _Provider:
        provider_name = "openrouter"

        def chat(
            self,
            messages: list[Any],
            tools: Any = None,
            config: Any = None,
        ) -> AsyncIterator[StreamEvent]:
            return self._chat(messages, tools=tools, config=config)

        async def _chat(
            self,
            messages: list[Any],
            *,
            tools: Any = None,
            config: Any = None,
        ) -> AsyncIterator[StreamEvent]:
            yield EnsembleProgressEvent(
                event_type="proposer_start",
                proposer_index=2,
                proposer_label="proposer_3",
                proposer_model="qwen/qwen3.7-max",
                proposer_provider="openrouter",
                sample_index=0,
                elapsed_ms=123,
                input_tokens=11,
                output_tokens=22,
                cost_usd=0.003,
                error="",
            )
            yield DoneEvent(model="qwen/qwen3.7-max")

        async def list_models(self) -> list[Any]:
            return []

    class _Selector:
        current_config = ProviderConfig(provider="openrouter", model="qwen/qwen3.7-max")

    provider = _SelectorFallbackProvider(_Provider(), _Selector())

    events = [event async for event in provider.chat([])]

    assert isinstance(events[0], EngineEnsembleProgressEvent)
    assert events[0].event_type == "proposer_start"
    assert events[0].proposer_index == 2
    assert events[0].proposer_label == "proposer_3"
    assert events[0].proposer_model == "qwen/qwen3.7-max"
    assert events[0].proposer_provider == "openrouter"
    assert events[0].sample_index == 0
    assert events[0].elapsed_ms == 123
    assert events[0].input_tokens == 11
    assert events[0].output_tokens == 22
    assert events[0].cost_usd == 0.003
    assert events[0].error == ""


def _static_b5_gateway_config() -> Any:
    from opensquilla.gateway.config import GatewayConfig

    return GatewayConfig(
        llm_ensemble={"enabled": True, "selection_mode": "static_openrouter_b5"},
    )


def test_static_b5_credential_unavailable_for_keyless_non_openrouter_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.provider.ensemble import static_openrouter_b5_credential_available

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    inherited = ProviderConfig(provider="groq", model="m", api_key="sk-groq-synthetic")

    assert static_openrouter_b5_credential_available(_static_b5_gateway_config(), inherited) is (
        False
    )


def test_static_b5_credential_env_key_is_an_opt_in_for_other_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.provider.ensemble import static_openrouter_b5_credential_available

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-synthetic")
    inherited = ProviderConfig(provider="groq", model="m", api_key="sk-groq-synthetic")

    assert static_openrouter_b5_credential_available(_static_b5_gateway_config(), inherited) is (
        True
    )


def test_static_b5_credential_resolves_from_inherited_openrouter_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.provider.ensemble import static_openrouter_b5_credential_available

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    inherited = ProviderConfig(provider="openrouter", model="m", api_key="sk-or-synthetic")

    assert static_openrouter_b5_credential_available(_static_b5_gateway_config(), inherited) is (
        True
    )


def test_static_b5_credential_unavailable_for_keyless_openrouter_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.provider.ensemble import static_openrouter_b5_credential_available

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    inherited = ProviderConfig(provider="openrouter", model="m", api_key="")

    assert static_openrouter_b5_credential_available(_static_b5_gateway_config(), inherited) is (
        False
    )


def test_static_b5_credential_accepts_non_selector_provider_config_shapes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The gateway floor/doctor call sites pass ``config.llm`` (no org_id field)."""
    from opensquilla.gateway.config import LlmProviderConfig
    from opensquilla.provider.ensemble import static_openrouter_b5_credential_available

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    config = _static_b5_gateway_config()

    keyless = LlmProviderConfig(provider="groq", model="m", api_key="sk-groq-synthetic")
    assert static_openrouter_b5_credential_available(config, keyless) is False

    keyed = LlmProviderConfig(provider="openrouter", model="m", api_key="sk-or-synthetic")
    assert static_openrouter_b5_credential_available(config, keyed) is True


def test_static_b5_credential_gate_agrees_with_config_side_floor_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.gateway.config import (
        GatewayConfig,
        static_openrouter_b5_ensemble_active,
        static_openrouter_b5_ensemble_enabled,
    )
    from opensquilla.provider.ensemble import static_openrouter_b5_credential_available

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    configs = [
        GatewayConfig(llm={"provider": "groq", "api_key": "sk-groq-synthetic"}),
        GatewayConfig(llm={"provider": "openrouter", "api_key": "sk-or-synthetic"}),
        GatewayConfig(llm={"provider": "openrouter", "api_key": ""}),
        GatewayConfig(
            llm={"provider": "groq", "api_key": ""},
            llm_ensemble={"enabled": True, "selection_mode": "router_dynamic"},
        ),
    ]
    for config in configs:
        expected = static_openrouter_b5_ensemble_enabled(
            config
        ) and static_openrouter_b5_credential_available(config, config.llm)
        assert static_openrouter_b5_ensemble_active(config) is expected
