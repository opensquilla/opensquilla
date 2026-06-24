from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import Any

import pytest

from opensquilla.provider.ensemble import EnsembleMemberConfig, EnsembleProvider
from opensquilla.provider.selector import ProviderConfig
from opensquilla.provider.types import (
    DoneEvent,
    ErrorEvent,
    Message,
    TextDeltaEvent,
    ToolDefinition,
    ToolInputSchema,
)


class _FakeProvider:
    def __init__(
        self,
        cfg: ProviderConfig,
        calls: list[dict[str, Any]],
        factories: dict[str, Callable[[list[Message], Any], list[Any]]],
    ) -> None:
        self.provider_name = cfg.provider
        self.model = cfg.model
        self._calls = calls
        self._factories = factories

    async def chat(
        self,
        messages: list[Message],
        tools: Any = None,
        config: Any = None,
    ) -> AsyncIterator[Any]:
        self._calls.append(
            {
                "model": self.model,
                "tools": tools,
                "messages": messages,
                "config": config,
            }
        )
        for event in self._factories[self.model](messages, tools):
            yield event

    async def list_models(self) -> list[Any]:
        return []


class _FallbackProvider:
    provider_name = "fallback"

    async def chat(
        self,
        messages: list[Message],
        tools: Any = None,
        config: Any = None,
    ) -> AsyncIterator[Any]:
        yield TextDeltaEvent(text="fallback answer")
        yield DoneEvent(input_tokens=3, output_tokens=2, model="fallback-model")

    async def list_models(self) -> list[Any]:
        return []


def _member(model: str, *, k: int = 1) -> EnsembleMemberConfig:
    return EnsembleMemberConfig(
        provider_config=ProviderConfig(
            provider="openrouter",
            model=model,
            api_key="sk-test",
            base_url="https://openrouter.ai/api",
        ),
        k=k,
    )


@pytest.mark.asyncio
async def test_ensemble_runs_proposers_text_only_and_aggregator_with_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    def _events(model: str, text: str, in_tokens: int, out_tokens: int):
        return lambda _messages, _tools: [
            TextDeltaEvent(text=text),
            DoneEvent(
                input_tokens=in_tokens,
                output_tokens=out_tokens,
                billed_cost=0.01 * in_tokens,
                model=model,
                cost_source="provider_billed",
            ),
        ]

    factories = {
        "p1": _events("p1", "draft from p1", 10, 2),
        "p2": _events("p2", "draft from p2", 11, 3),
        "agg": _events("agg", "final fused", 20, 5),
    }

    def fake_build_provider(cfg: ProviderConfig) -> _FakeProvider:
        return _FakeProvider(cfg, calls, factories)

    monkeypatch.setattr("opensquilla.provider.selector._build_provider", fake_build_provider)
    provider = EnsembleProvider(
        profile_name="test",
        proposers=[_member("p1"), _member("p2")],
        aggregator=_member("agg"),
        record_candidates=True,
        shuffle_candidates=False,
    )
    tool = ToolDefinition(
        name="search",
        description="Search",
        input_schema=ToolInputSchema(),
    )

    events = [
        event
        async for event in provider.chat(
            [Message(role="user", content="solve it")],
            tools=[tool],
        )
    ]

    assert [event.kind for event in events] == ["provider_heartbeat", "text_delta", "done"]
    assert events[1].text == "final fused"
    done = events[-1]
    assert isinstance(done, DoneEvent)
    assert done.input_tokens == 41
    assert done.output_tokens == 10
    assert done.model == "agg"
    assert [row["model"] for row in done.model_usage_breakdown] == ["p1", "p2", "agg"]
    assert done.ensemble_trace["successful_proposers"] == 2
    assert "draft from p1" in done.ensemble_trace["candidates"][0]["text"]
    assert calls[0]["model"] in {"p1", "p2"}
    proposer_calls = [call for call in calls if call["model"] in {"p1", "p2"}]
    assert all(call["tools"] is None for call in proposer_calls)
    aggregator_call = next(call for call in calls if call["model"] == "agg")
    assert aggregator_call["tools"] == [tool]
    assert "Candidate drafts" in aggregator_call["messages"][-1].content


@pytest.mark.asyncio
async def test_ensemble_all_failed_uses_single_model_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []
    factories = {
        "p1": lambda _messages, _tools: [ErrorEvent(message="nope", code="bad")],
        "p2": lambda _messages, _tools: [ErrorEvent(message="also nope", code="bad")],
    }

    def fake_build_provider(cfg: ProviderConfig) -> _FakeProvider:
        return _FakeProvider(cfg, calls, factories)

    monkeypatch.setattr("opensquilla.provider.selector._build_provider", fake_build_provider)
    provider = EnsembleProvider(
        profile_name="test",
        proposers=[_member("p1"), _member("p2")],
        aggregator=_member("agg"),
        fallback_provider=_FallbackProvider(),
    )

    events = [event async for event in provider.chat([Message(role="user", content="solve")])]

    assert [event.kind for event in events] == ["provider_heartbeat", "text_delta", "done"]
    assert events[1].text == "fallback answer"
    done = events[-1]
    assert isinstance(done, DoneEvent)
    assert done.ensemble_trace["fallback_used"] is True
    assert done.ensemble_trace["successful_proposers"] == 0
    assert [row["model"] for row in done.model_usage_breakdown] == ["fallback-model"]


@pytest.mark.asyncio
async def test_ensemble_insufficient_success_fallback_includes_proposer_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []
    factories = {
        "p1": lambda _messages, _tools: [
            TextDeltaEvent(text="usable but below min"),
            DoneEvent(input_tokens=5, output_tokens=2, billed_cost=0.01, model="p1"),
        ],
        "p2": lambda _messages, _tools: [ErrorEvent(message="rate limited", code="429")],
    }

    def fake_build_provider(cfg: ProviderConfig) -> _FakeProvider:
        return _FakeProvider(cfg, calls, factories)

    monkeypatch.setattr("opensquilla.provider.selector._build_provider", fake_build_provider)
    provider = EnsembleProvider(
        profile_name="test",
        proposers=[_member("p1"), _member("p2")],
        aggregator=_member("agg"),
        fallback_provider=_FallbackProvider(),
        min_successful_proposers=2,
    )

    events = [event async for event in provider.chat([Message(role="user", content="solve")])]
    done = events[-1]

    assert isinstance(done, DoneEvent)
    assert done.ensemble_trace["fallback_used"] is True
    assert done.input_tokens == 8
    assert done.output_tokens == 4
    assert [row["model"] for row in done.model_usage_breakdown] == ["p1", "fallback-model"]
    assert [row["role"] for row in done.model_usage_breakdown] == [
        "proposer",
        "fallback_single",
    ]


@pytest.mark.asyncio
async def test_ensemble_partial_failure_still_aggregates_when_min_success_met(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []
    factories = {
        "p1": lambda _messages, _tools: [
            TextDeltaEvent(text="usable draft"),
            DoneEvent(input_tokens=5, output_tokens=2, model="p1"),
        ],
        "p2": lambda _messages, _tools: [ErrorEvent(message="rate limited", code="429")],
        "agg": lambda _messages, _tools: [
            TextDeltaEvent(text="aggregated"),
            DoneEvent(input_tokens=7, output_tokens=3, model="agg"),
        ],
    }

    def fake_build_provider(cfg: ProviderConfig) -> _FakeProvider:
        return _FakeProvider(cfg, calls, factories)

    monkeypatch.setattr("opensquilla.provider.selector._build_provider", fake_build_provider)
    provider = EnsembleProvider(
        profile_name="test",
        proposers=[_member("p1"), _member("p2")],
        aggregator=_member("agg"),
        min_successful_proposers=1,
    )

    events = [event async for event in provider.chat([Message(role="user", content="solve")])]
    done = events[-1]

    assert isinstance(done, DoneEvent)
    assert done.model == "agg"
    assert done.ensemble_trace["successful_proposers"] == 1
    failed = [row for row in done.ensemble_trace["candidates"] if not row["ok"]]
    assert failed[0]["error_code"] == "429"
    assert [row["model"] for row in done.model_usage_breakdown] == ["p1", "agg"]


@pytest.mark.asyncio
async def test_ensemble_aggregator_error_preserves_proposer_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    def _raise_aggregator(_messages: list[Message], _tools: Any) -> list[Any]:
        raise RuntimeError("aggregator broke")

    factories = {
        "p1": lambda _messages, _tools: [
            TextDeltaEvent(text="usable draft"),
            DoneEvent(
                input_tokens=5,
                output_tokens=2,
                billed_cost=0.25,
                model="p1",
                cost_source="provider_billed",
            ),
        ],
        "agg": _raise_aggregator,
    }

    def fake_build_provider(cfg: ProviderConfig) -> _FakeProvider:
        return _FakeProvider(cfg, calls, factories)

    monkeypatch.setattr("opensquilla.provider.selector._build_provider", fake_build_provider)
    provider = EnsembleProvider(
        profile_name="test",
        proposers=[_member("p1")],
        aggregator=_member("agg"),
        record_candidates=True,
    )

    events = [event async for event in provider.chat([Message(role="user", content="solve")])]

    assert [event.kind for event in events] == ["provider_heartbeat", "error"]
    error = events[-1]
    assert isinstance(error, ErrorEvent)
    assert error.code == "ensemble_aggregator_error"
    assert error.diagnostic_done is not None
    assert error.diagnostic_done.billed_cost == 0.25
    assert [row["model"] for row in error.diagnostic_done.model_usage_breakdown] == ["p1"]
    assert error.diagnostic_done.ensemble_trace["successful_proposers"] == 1
    assert error.diagnostic_done.ensemble_trace["aggregator_error"]["code"] == (
        "ensemble_aggregator_error"
    )
