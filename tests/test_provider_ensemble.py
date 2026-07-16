from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Callable
from typing import Any

import pytest

from opensquilla.provider.ensemble import (
    EnsembleMemberConfig,
    EnsembleProvider,
    _bounded_candidate_tool_calls,
    _tool_calls_json,
    _truncate_text,
)
from opensquilla.provider.selector import ProviderConfig
from opensquilla.provider.types import (
    DoneEvent,
    ErrorEvent,
    Message,
    TextDeltaEvent,
    ToolDefinition,
    ToolInputSchema,
    ToolUseDeltaEvent,
    ToolUseEndEvent,
    ToolUseStartEvent,
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


class _DelayedProvider:
    def __init__(
        self,
        cfg: ProviderConfig,
        calls: list[dict[str, Any]],
        delays: dict[str, float],
    ) -> None:
        self.provider_name = cfg.provider
        self.model = cfg.model
        self._calls = calls
        self._delays = delays

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
        delay = self._delays.get(self.model, 0.0)
        if delay > 0:
            await asyncio.sleep(delay)
        yield TextDeltaEvent(text=f"draft from {self.model}")
        yield DoneEvent(input_tokens=1, output_tokens=1, model=self.model)

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


def test_empty_tool_calls_do_not_consume_candidate_budget() -> None:
    assert _bounded_candidate_tool_calls([], 400) == ([], 0, False)


def test_candidate_budget_is_strict_at_small_text_and_tool_boundaries() -> None:
    call = {
        "tool_use_id": "proposal-edge",
        "name": "search",
        "arguments": {"query": "x" * 279},
        "synthetic_from_text": False,
    }
    bounded, tool_chars, truncated = _bounded_candidate_tool_calls([call], 400)
    assert truncated is False
    assert tool_chars == len(_tool_calls_json(bounded))
    remaining = 400 - tool_chars
    text = _truncate_text("y" * 20, remaining, strict_budget=True)
    assert len(text) + tool_chars <= 400

    assert _bounded_candidate_tool_calls([call], 1) == ([], 0, True)


@pytest.mark.asyncio
async def test_ensemble_default_off_flattens_unsolicited_tool_events_like_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []
    factories = {
        "p1": lambda _messages, _tools: [
            TextDeltaEvent(text="legacy narration"),
            ToolUseStartEvent(tool_use_id="unsolicited-1", tool_name="search"),
            ToolUseDeltaEvent(
                tool_use_id="unsolicited-1",
                json_fragment='{"query":"legacy"}',
            ),
            ToolUseEndEvent(
                tool_use_id="unsolicited-1",
                tool_name="search",
                arguments={"query": "legacy"},
            ),
            DoneEvent(input_tokens=10, output_tokens=3, model="p1"),
        ],
        "agg": lambda _messages, _tools: [
            TextDeltaEvent(text="final"),
            DoneEvent(input_tokens=20, output_tokens=4, model="agg"),
        ],
    }

    def fake_build_provider(cfg: ProviderConfig) -> _FakeProvider:
        return _FakeProvider(cfg, calls, factories)

    monkeypatch.setattr("opensquilla.provider.selector._build_provider", fake_build_provider)
    provider = EnsembleProvider(
        profile_name="test",
        proposers=[_member("p1")],
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
            [Message(role="user", content="research")],
            tools=[tool],
        )
    ]

    proposer_call = next(call for call in calls if call["model"] == "p1")
    aggregator_call = next(call for call in calls if call["model"] == "agg")
    assert proposer_call["tools"] is None
    assert aggregator_call["tools"] == [tool]
    assert "<PROPOSED_TOOL_CALLS" not in str(aggregator_call["messages"][-1].content)
    candidate = events[-1].ensemble_trace["candidates"][0]
    assert candidate["tool_call_count"] == 0
    assert candidate["text"] == (
        "legacy narration\n[tool_use:search]{\"query\":\"legacy\"}\n[tool_args:{'query': 'legacy'}]"
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
    assert done.ensemble_trace["proposer_tools_enabled"] is False
    assert done.ensemble_trace["shuffle_candidates"] is False
    assert done.ensemble_trace["final_request_role"] == "aggregator"
    assert done.ensemble_trace["llm_request_count"] == 3
    assert "candidate_prefilter" not in done.ensemble_trace
    assert "selected_candidate_indexes" not in done.ensemble_trace
    assert "draft from p1" in done.ensemble_trace["candidates"][0]["text"]
    assert calls[0]["model"] in {"p1", "p2"}
    proposer_calls = [call for call in calls if call["model"] in {"p1", "p2"}]
    assert all(call["tools"] is None for call in proposer_calls)
    aggregator_call = next(call for call in calls if call["model"] == "agg")
    assert aggregator_call["tools"] == [tool]
    assert "Candidate drafts" in aggregator_call["messages"][-1].content
    requests = done.ensemble_trace["requests"]
    assert [request["role"] for request in requests] == [
        "proposer",
        "proposer",
        "aggregator",
    ]
    assert [request["model"] for request in requests] == ["p1", "p2", "agg"]
    assert requests[0]["messages"][0]["content"] == "solve it"
    assert requests[0]["params"]["effective_config"]["timeout"] == 120.0
    assert requests[-1]["tool_count"] == 1
    assert requests[-1]["tools"][0]["name"] == "search"
    assert "Candidate drafts" in requests[-1]["messages"][-1]["content"]


@pytest.mark.asyncio
async def test_ensemble_preserves_structured_proposer_tool_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    factories = {
        "p1": lambda _messages, _tools: [
            ToolUseStartEvent(tool_use_id="proposal-1", tool_name="search"),
            ToolUseDeltaEvent(
                tool_use_id="proposal-1",
                json_fragment='{"query":"latest evidence"}',
            ),
            ToolUseEndEvent(
                tool_use_id="proposal-1",
                tool_name="search",
                arguments={"query": "latest evidence"},
            ),
            DoneEvent(input_tokens=10, output_tokens=3, model="p1"),
        ],
        "agg": lambda _messages, _tools: [
            ToolUseStartEvent(tool_use_id="chosen-1", tool_name="search"),
            ToolUseDeltaEvent(
                tool_use_id="chosen-1",
                json_fragment='{"query":"latest evidence"}',
            ),
            ToolUseEndEvent(
                tool_use_id="chosen-1",
                tool_name="search",
                arguments={"query": "latest evidence"},
            ),
            DoneEvent(input_tokens=20, output_tokens=4, model="agg"),
        ],
    }

    def fake_build_provider(cfg: ProviderConfig) -> _FakeProvider:
        return _FakeProvider(cfg, calls, factories)

    monkeypatch.setattr("opensquilla.provider.selector._build_provider", fake_build_provider)
    provider = EnsembleProvider(
        profile_name="test",
        proposers=[_member("p1")],
        aggregator=_member("agg"),
        record_candidates=True,
        shuffle_candidates=False,
        proposer_tools=True,
    )
    tool = ToolDefinition(
        name="search",
        description="Search",
        input_schema=ToolInputSchema(),
    )

    events = [
        event
        async for event in provider.chat(
            [Message(role="user", content="research it")],
            tools=[tool],
        )
    ]

    assert [event.kind for event in events] == [
        "provider_heartbeat",
        "tool_use_start",
        "tool_use_delta",
        "tool_use_end",
        "done",
    ]
    proposer_call = next(call for call in calls if call["model"] == "p1")
    assert proposer_call["tools"] == [tool]
    aggregator_call = next(call for call in calls if call["model"] == "agg")
    assert aggregator_call["tools"] == [tool]
    prompt = str(aggregator_call["messages"][-1].content)
    assert '<PROPOSED_TOOL_CALLS status="not_executed" truncated="false">' in prompt
    assert '"name": "search"' in prompt
    assert '"query": "latest evidence"' in prompt
    assert "fresh structured call" in prompt
    assert "[tool_use:" not in prompt

    done = events[-1]
    assert isinstance(done, DoneEvent)
    assert done.ensemble_trace["proposer_tools_enabled"] is True
    candidate = done.ensemble_trace["candidates"][0]
    assert candidate["ok"] is True
    assert candidate["text"] == ""
    assert candidate["tool_call_count"] == 1
    assert candidate["tool_calls"] == [
        {
            "tool_use_id": "proposal-1",
            "name": "search",
            "arguments": {"query": "latest evidence"},
            "synthetic_from_text": False,
        }
    ]
    proposer_request = done.ensemble_trace["requests"][0]
    assert proposer_request["role"] == "proposer"
    assert proposer_request["tool_count"] == 1
    assert proposer_request["tools"][0]["name"] == "search"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("case", "expected_diagnostic"),
    [
        ("orphan_end", "orphan_tool_end"),
        ("orphan_delta", "orphan_tool_delta"),
        ("empty_id", "empty_tool_use_id"),
        ("empty_name", "empty_tool_name"),
        ("duplicate_start", "duplicate_tool_start"),
        ("duplicate_end", "duplicate_tool_end"),
        ("incomplete", "incomplete_tool_call"),
        ("invalid_json", "invalid_tool_argument_json"),
        ("null_json", "non_object_tool_argument_json"),
        ("list_json", "non_object_tool_argument_json"),
        ("non_object_end", "non_object_tool_arguments"),
        ("non_json_end", "non_json_tool_arguments"),
        ("raw_end", "unparsed_raw_tool_arguments"),
        ("raw_delta", "unparsed_raw_tool_arguments"),
        ("unoffered", "unoffered_tool_name"),
        ("name_mismatch", "tool_name_mismatch"),
        ("args_mismatch", "tool_arguments_mismatch"),
        ("after_done", "event_after_done"),
    ],
)
async def test_ensemble_rejects_malformed_structured_proposer_tool_streams(
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    expected_diagnostic: str,
) -> None:
    calls: list[dict[str, Any]] = []
    start = ToolUseStartEvent(tool_use_id="proposal-1", tool_name="search")
    end = ToolUseEndEvent(
        tool_use_id="proposal-1",
        tool_name="search",
        arguments={"query": "one"},
    )
    done = DoneEvent(input_tokens=10, output_tokens=3, model="p1")
    cases: dict[str, list[Any]] = {
        "orphan_end": [end, done],
        "orphan_delta": [
            ToolUseDeltaEvent(tool_use_id="missing", json_fragment="{}"),
            done,
        ],
        "empty_id": [
            ToolUseStartEvent(tool_use_id="", tool_name="search"),
            done,
        ],
        "empty_name": [
            ToolUseStartEvent(tool_use_id="proposal-1", tool_name=""),
            ToolUseEndEvent(
                tool_use_id="proposal-1",
                tool_name="",
                arguments={},
            ),
            done,
        ],
        "duplicate_start": [start, start, end, done],
        "duplicate_end": [start, end, end, done],
        "incomplete": [start, done],
        "invalid_json": [
            start,
            ToolUseDeltaEvent(tool_use_id="proposal-1", json_fragment="{bad"),
            ToolUseEndEvent(
                tool_use_id="proposal-1",
                tool_name="search",
                arguments={},
            ),
            done,
        ],
        "null_json": [
            start,
            ToolUseDeltaEvent(tool_use_id="proposal-1", json_fragment="null"),
            ToolUseEndEvent(
                tool_use_id="proposal-1",
                tool_name="search",
                arguments={},
            ),
            done,
        ],
        "list_json": [
            start,
            ToolUseDeltaEvent(tool_use_id="proposal-1", json_fragment="[]"),
            ToolUseEndEvent(
                tool_use_id="proposal-1",
                tool_name="search",
                arguments={},
            ),
            done,
        ],
        "non_object_end": [
            start,
            ToolUseEndEvent(
                tool_use_id="proposal-1",
                tool_name="search",
                arguments=["not", "an", "object"],  # type: ignore[arg-type]
            ),
            done,
        ],
        "non_json_end": [
            start,
            ToolUseEndEvent(
                tool_use_id="proposal-1",
                tool_name="search",
                arguments={"query": b"not-json"},
            ),
            done,
        ],
        "raw_end": [
            start,
            ToolUseEndEvent(
                tool_use_id="proposal-1",
                tool_name="search",
                arguments={"_raw": "{bad"},
            ),
            done,
        ],
        "raw_delta": [
            start,
            ToolUseDeltaEvent(
                tool_use_id="proposal-1",
                json_fragment='{"_raw":"{bad"}',
            ),
            ToolUseEndEvent(
                tool_use_id="proposal-1",
                tool_name="search",
                arguments={},
            ),
            done,
        ],
        "unoffered": [
            ToolUseStartEvent(tool_use_id="proposal-1", tool_name="write"),
            ToolUseEndEvent(
                tool_use_id="proposal-1",
                tool_name="write",
                arguments={"value": "one"},
            ),
            done,
        ],
        "name_mismatch": [
            start,
            ToolUseEndEvent(
                tool_use_id="proposal-1",
                tool_name="write",
                arguments={"query": "one"},
            ),
            done,
        ],
        "args_mismatch": [
            start,
            ToolUseDeltaEvent(
                tool_use_id="proposal-1",
                json_fragment='{"query":"one"}',
            ),
            ToolUseEndEvent(
                tool_use_id="proposal-1",
                tool_name="search",
                arguments={"query": "two"},
            ),
            done,
        ],
        "after_done": [done, start, end],
    }
    factories = {"p1": lambda _messages, _tools: cases[case]}

    def fake_build_provider(cfg: ProviderConfig) -> _FakeProvider:
        return _FakeProvider(cfg, calls, factories)

    monkeypatch.setattr("opensquilla.provider.selector._build_provider", fake_build_provider)
    provider = EnsembleProvider(
        profile_name="test",
        proposers=[_member("p1")],
        aggregator=_member("agg"),
        fallback_provider=_FallbackProvider(),
        record_candidates=True,
        shuffle_candidates=False,
        proposer_tools=True,
    )
    tool = ToolDefinition(
        name="search",
        description="Search",
        input_schema=ToolInputSchema(),
    )

    events = [
        event
        async for event in provider.chat(
            [Message(role="user", content="research")],
            tools=[tool],
        )
    ]

    fallback_done = events[-1]
    assert isinstance(fallback_done, DoneEvent)
    candidate = fallback_done.ensemble_trace["candidates"][0]
    assert candidate["ok"] is False
    assert candidate["error_code"] == "malformed_tool_stream"
    assert candidate["tool_call_count"] == 0
    assert any(expected_diagnostic in diagnostic for diagnostic in candidate["tool_call_errors"])


@pytest.mark.asyncio
async def test_ensemble_preserves_interleaved_tool_calls_in_start_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []
    factories = {
        "p1": lambda _messages, _tools: [
            ToolUseStartEvent(tool_use_id="call-a", tool_name="search"),
            ToolUseStartEvent(tool_use_id="call-b", tool_name="fetch"),
            ToolUseDeltaEvent(
                tool_use_id="call-b",
                json_fragment='{"url":"https://example.com"}',
            ),
            ToolUseDeltaEvent(
                tool_use_id="call-a",
                json_fragment='{"query":"evidence"}',
            ),
            ToolUseEndEvent(
                tool_use_id="call-b",
                tool_name="fetch",
                arguments={"url": "https://example.com"},
            ),
            ToolUseEndEvent(
                tool_use_id="call-a",
                tool_name="search",
                arguments={"query": "evidence"},
            ),
            DoneEvent(input_tokens=10, output_tokens=3, model="p1"),
        ],
        "agg": lambda _messages, _tools: [
            TextDeltaEvent(text="final"),
            DoneEvent(input_tokens=20, output_tokens=4, model="agg"),
        ],
    }

    def fake_build_provider(cfg: ProviderConfig) -> _FakeProvider:
        return _FakeProvider(cfg, calls, factories)

    monkeypatch.setattr("opensquilla.provider.selector._build_provider", fake_build_provider)
    provider = EnsembleProvider(
        profile_name="test",
        proposers=[_member("p1")],
        aggregator=_member("agg"),
        record_candidates=True,
        shuffle_candidates=False,
        proposer_tools=True,
    )
    tools = [
        ToolDefinition(
            name="search",
            description="Search",
            input_schema=ToolInputSchema(),
        ),
        ToolDefinition(
            name="fetch",
            description="Fetch",
            input_schema=ToolInputSchema(),
        ),
    ]

    events = [
        event
        async for event in provider.chat(
            [Message(role="user", content="research")],
            tools=tools,
        )
    ]

    candidate = events[-1].ensemble_trace["candidates"][0]
    assert [call["tool_use_id"] for call in candidate["tool_calls"]] == [
        "call-a",
        "call-b",
    ]
    assert [call["name"] for call in candidate["tool_calls"]] == [
        "search",
        "fetch",
    ]


@pytest.mark.asyncio
async def test_ensemble_removes_synthetic_tool_protocol_from_candidate_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []
    factories = {
        "p1": lambda _messages, _tools: [
            TextDeltaEvent(
                text='useful analysis\nsearch{"query":"latest evidence"}'
            ),
            ToolUseStartEvent(
                tool_use_id="synthetic-1",
                tool_name="search",
                synthetic_from_text=True,
            ),
            ToolUseEndEvent(
                tool_use_id="synthetic-1",
                tool_name="search",
                arguments={"query": "latest evidence"},
                synthetic_from_text=True,
            ),
            DoneEvent(input_tokens=10, output_tokens=3, model="p1"),
        ],
        "agg": lambda _messages, _tools: [
            TextDeltaEvent(text="final"),
            DoneEvent(input_tokens=20, output_tokens=4, model="agg"),
        ],
    }

    def fake_build_provider(cfg: ProviderConfig) -> _FakeProvider:
        return _FakeProvider(cfg, calls, factories)

    monkeypatch.setattr("opensquilla.provider.selector._build_provider", fake_build_provider)
    provider = EnsembleProvider(
        profile_name="test",
        proposers=[_member("p1")],
        aggregator=_member("agg"),
        record_candidates=True,
        shuffle_candidates=False,
        proposer_tools=True,
    )
    tool = ToolDefinition(
        name="search",
        description="Search",
        input_schema=ToolInputSchema(),
    )

    events = [
        event
        async for event in provider.chat(
            [Message(role="user", content="research")],
            tools=[tool],
        )
    ]

    candidate = events[-1].ensemble_trace["candidates"][0]
    assert candidate["text"] == "useful analysis"
    aggregator_prompt = str(
        next(call for call in calls if call["model"] == "agg")["messages"][-1].content
    )
    assert 'search{"query":"latest evidence"}' not in aggregator_prompt
    assert '"synthetic_from_text": true' in aggregator_prompt


@pytest.mark.asyncio
async def test_ensemble_bounds_and_hashes_malformed_tool_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []
    secret = "model-controlled-secret"
    factories = {
        "p1": lambda _messages, _tools: [
            *[
                ToolUseDeltaEvent(
                    tool_use_id=f"{secret}-{index}-" + ("x" * 500),
                    json_fragment="{}",
                )
                for index in range(100)
            ],
            DoneEvent(input_tokens=10, output_tokens=3, model="p1"),
        ]
    }

    def fake_build_provider(cfg: ProviderConfig) -> _FakeProvider:
        return _FakeProvider(cfg, calls, factories)

    monkeypatch.setattr("opensquilla.provider.selector._build_provider", fake_build_provider)
    provider = EnsembleProvider(
        profile_name="test",
        proposers=[_member("p1")],
        aggregator=_member("agg"),
        fallback_provider=_FallbackProvider(),
        record_candidates=True,
        shuffle_candidates=False,
        proposer_tools=True,
    )
    tool = ToolDefinition(
        name="search",
        description="Search",
        input_schema=ToolInputSchema(),
    )

    events = [
        event
        async for event in provider.chat(
            [Message(role="user", content="research")],
            tools=[tool],
        )
    ]

    candidate = events[-1].ensemble_trace["candidates"][0]
    assert candidate["tool_call_error_count"] == 100
    assert len(candidate["tool_call_errors"]) == 32
    assert candidate["tool_call_errors_truncated"] is True
    assert secret not in json.dumps(candidate)


@pytest.mark.asyncio
async def test_ensemble_bounds_proposer_tool_arguments_with_candidate_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []
    oversized_query = "x" * 2_000
    factories = {
        "p1": lambda _messages, _tools: [
            TextDeltaEvent(text="draft " * 200),
            ToolUseStartEvent(tool_use_id="proposal-large", tool_name="search"),
            ToolUseEndEvent(
                tool_use_id="proposal-large",
                tool_name="search",
                arguments={"query": oversized_query},
            ),
            DoneEvent(input_tokens=10, output_tokens=3, model="p1"),
        ],
        "agg": lambda _messages, _tools: [
            TextDeltaEvent(text="final"),
            DoneEvent(input_tokens=20, output_tokens=4, model="agg"),
        ],
    }

    def fake_build_provider(cfg: ProviderConfig) -> _FakeProvider:
        return _FakeProvider(cfg, calls, factories)

    monkeypatch.setattr("opensquilla.provider.selector._build_provider", fake_build_provider)
    provider = EnsembleProvider(
        profile_name="test",
        proposers=[_member("p1")],
        aggregator=_member("agg"),
        record_candidates=True,
        shuffle_candidates=False,
        proposer_tools=True,
        candidate_max_chars=400,
    )
    tool = ToolDefinition(
        name="search",
        description="Search",
        input_schema=ToolInputSchema(),
    )

    events = [
        event
        async for event in provider.chat(
            [Message(role="user", content="research it")],
            tools=[tool],
        )
    ]

    done = events[-1]
    assert isinstance(done, DoneEvent)
    candidate = done.ensemble_trace["candidates"][0]
    assert candidate["ok"] is True
    assert candidate["tool_calls_truncated"] is True
    assert candidate["tool_calls"][0]["arguments"]["_truncated"] is True
    assert candidate["tool_calls"][0]["arguments"]["_original_chars"] > 2_000
    candidate_chars = len(candidate["text"]) + len(
        json.dumps(candidate["tool_calls"], sort_keys=True)
    )
    assert candidate_chars <= 400
    aggregator_prompt = str(
        next(call for call in calls if call["model"] == "agg")["messages"][-1].content
    )
    assert 'truncated="true"' in aggregator_prompt
    assert oversized_query not in aggregator_prompt


@pytest.mark.asyncio
async def test_ensemble_expands_proposer_k_into_multiple_samples(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    def _events(model: str, text: str, in_tokens: int, out_tokens: int):
        return lambda _messages, _tools: [
            TextDeltaEvent(text=text),
            DoneEvent(input_tokens=in_tokens, output_tokens=out_tokens, model=model),
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
        proposers=[_member("p1", k=2), _member("p2")],
        aggregator=_member("agg"),
        record_candidates=True,
        shuffle_candidates=False,
    )

    events = [event async for event in provider.chat([Message(role="user", content="solve")])]

    done = events[-1]
    assert isinstance(done, DoneEvent)
    assert done.ensemble_trace["total_candidates"] == 3
    assert done.ensemble_trace["llm_request_count"] == 4
    assert [row["model"] for row in done.model_usage_breakdown] == [
        "p1",
        "p1",
        "p2",
        "agg",
    ]
    assert [row["sample_index"] for row in done.model_usage_breakdown] == [0, 1, 0, 0]
    assert [candidate["sample_index"] for candidate in done.ensemble_trace["candidates"]] == [
        0,
        1,
        0,
    ]
    assert [call["model"] for call in calls].count("p1") == 2


@pytest.mark.asyncio
async def test_ensemble_can_early_stop_slow_proposers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []
    delays = {
        "fast": 0.0,
        "slow": 1.0,
        "agg": 0.0,
    }

    def fake_build_provider(cfg: ProviderConfig) -> _DelayedProvider:
        return _DelayedProvider(cfg, calls, delays)

    monkeypatch.setattr("opensquilla.provider.selector._build_provider", fake_build_provider)
    provider = EnsembleProvider(
        profile_name="test",
        proposers=[_member("fast"), _member("slow")],
        aggregator=_member("agg"),
        record_candidates=True,
        shuffle_candidates=False,
        proposer_early_stop_success_count=1,
        proposer_early_stop_after_seconds=0.02,
    )

    started = time.monotonic()
    events = [event async for event in provider.chat([Message(role="user", content="solve")])]
    elapsed = time.monotonic() - started

    assert elapsed < 0.5
    done = events[-1]
    assert isinstance(done, DoneEvent)
    trace = done.ensemble_trace
    assert trace["successful_proposers"] == 1
    assert trace["proposer_early_stop"] == {
        "enabled": True,
        "success_count": 1,
        "after_seconds": 0.02,
        "early_stopped_count": 1,
        "usage_unknown_count": 1,
        "cost_observed": False,
    }
    failed_candidate_codes = [
        candidate["error_code"]
        for candidate in trace["candidates"]
        if not candidate["ok"]
    ]
    assert failed_candidate_codes == ["early_stopped"]
    assert [row["model"] for row in done.model_usage_breakdown] == ["fast", "slow", "agg"]
    assert done.model_usage_breakdown[1]["cost_source"] == "unknown_canceled"
    assert done.cost_source == "unknown_canceled"
    proposer_requests = [
        request for request in trace["requests"] if request["role"] == "proposer"
    ]
    assert len(proposer_requests) == 2
    assert proposer_requests[1]["cancelled_before_done"] is True
    assert {call["model"] for call in calls[:2]} == {"fast", "slow"}
    assert calls[-1]["model"] == "agg"


@pytest.mark.asyncio
async def test_ensemble_two_layer_moa_refines_first_aggregation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []
    agg_calls = 0

    def _events(model: str, text: str, in_tokens: int, out_tokens: int):
        return lambda _messages, _tools: [
            TextDeltaEvent(text=text),
            DoneEvent(input_tokens=in_tokens, output_tokens=out_tokens, model=model),
        ]

    def _agg_events(messages: list[Message], _tools: Any) -> list[Any]:
        nonlocal agg_calls
        agg_calls += 1
        if agg_calls == 1:
            return [
                TextDeltaEvent(text="first fused"),
                DoneEvent(input_tokens=20, output_tokens=5, model="agg"),
            ]
        assert "Previous fused answer" in str(messages[-1].content)
        assert "first fused" in str(messages[-1].content)
        return [
            TextDeltaEvent(text="final refined"),
            DoneEvent(input_tokens=30, output_tokens=6, model="agg"),
        ]

    factories = {
        "p1": _events("p1", "draft from p1", 10, 2),
        "p2": _events("p2", "draft from p2", 11, 3),
        "agg": _agg_events,
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
        moa_layers=2,
    )
    tool = ToolDefinition(
        name="search",
        description="Search",
        input_schema=ToolInputSchema(),
    )

    events = [
        event
        async for event in provider.chat(
            [Message(role="user", content="solve")],
            tools=[tool],
        )
    ]

    assert [event.kind for event in events] == [
        "provider_heartbeat",
        "provider_heartbeat",
        "text_delta",
        "done",
    ]
    assert events[2].text == "final refined"
    done = events[-1]
    assert isinstance(done, DoneEvent)
    assert done.input_tokens == 71
    assert done.output_tokens == 16
    assert [row["role"] for row in done.model_usage_breakdown] == [
        "proposer",
        "proposer",
        "aggregator_layer_1",
        "aggregator",
    ]
    assert done.ensemble_trace["moa_layers"] == 2
    assert done.ensemble_trace["moa_refine_count"] == 1
    assert done.ensemble_trace["llm_request_count"] == 4
    aggregator_calls = [call for call in calls if call["model"] == "agg"]
    assert len(aggregator_calls) == 2
    assert aggregator_calls[0]["tools"] is None
    assert aggregator_calls[1]["tools"] == [tool]


@pytest.mark.asyncio
async def test_ensemble_select_best_candidate_outputs_chosen_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    def _events(model: str, text: str, in_tokens: int, out_tokens: int):
        return lambda _messages, _tools: [
            TextDeltaEvent(text=text),
            DoneEvent(input_tokens=in_tokens, output_tokens=out_tokens, model=model),
        ]

    factories = {
        "p1": _events("p1", "weaker draft", 10, 2),
        "p2": _events("p2", "stronger draft", 11, 3),
        "agg": _events(
            "agg",
            '{"selected_candidate_index":1,"rationale":"best"}',
            20,
            4,
        ),
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
        output_strategy="select_best_candidate",
    )
    tool = ToolDefinition(
        name="search",
        description="Search",
        input_schema=ToolInputSchema(),
    )

    events = [
        event
        async for event in provider.chat(
            [Message(role="user", content="solve")],
            tools=[tool],
        )
    ]

    assert [event.kind for event in events] == [
        "provider_heartbeat",
        "provider_heartbeat",
        "text_delta",
        "done",
    ]
    assert events[2].text == "stronger draft"
    done = events[-1]
    assert isinstance(done, DoneEvent)
    assert done.stop_reason == "selected_candidate"
    assert done.model == "p2"
    assert done.input_tokens == 41
    assert done.output_tokens == 9
    assert [row["role"] for row in done.model_usage_breakdown] == [
        "proposer",
        "proposer",
        "candidate_selector",
    ]
    assert done.model_usage_breakdown[-1]["label"] == "candidate_selector"
    assert done.ensemble_trace["output_strategy"] == "select_best_candidate"
    assert done.ensemble_trace["final_request_role"] == "candidate_selector"
    assert done.ensemble_trace["llm_request_count"] == 3
    assert done.ensemble_trace["selected_candidate_indexes"] == [1]
    assert done.ensemble_trace["candidate_selection"]["applied"] is True
    selector_call = next(call for call in calls if call["model"] == "agg")
    assert selector_call["tools"] is None
    assert "Select the single best candidate" in selector_call["messages"][-1].content


@pytest.mark.asyncio
async def test_ensemble_select_best_tool_candidate_requires_fresh_aggregator_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []
    oversized_query = "x" * 2_000
    factories = {
        "p1": lambda _messages, _tools: [
            ToolUseStartEvent(tool_use_id="proposal-1", tool_name="search"),
            ToolUseDeltaEvent(
                tool_use_id="proposal-1",
                json_fragment=json.dumps({"query": oversized_query}),
            ),
            ToolUseEndEvent(
                tool_use_id="proposal-1",
                tool_name="search",
                arguments={"query": oversized_query},
            ),
            DoneEvent(input_tokens=10, output_tokens=3, model="p1"),
        ],
        "p2": lambda _messages, _tools: [
            TextDeltaEvent(text="text alternative"),
            DoneEvent(input_tokens=11, output_tokens=2, model="p2"),
        ],
    }

    def aggregator_events(_messages: list[Message], tools: Any) -> list[Any]:
        if tools is None:
            return [
                TextDeltaEvent(text='{"selected_candidate_index":0,"rationale":"best action"}'),
                DoneEvent(input_tokens=20, output_tokens=4, model="agg"),
            ]
        return [
            ToolUseStartEvent(tool_use_id="authorized-1", tool_name="search"),
            ToolUseDeltaEvent(
                tool_use_id="authorized-1",
                json_fragment='{"query":"fresh bounded query"}',
            ),
            ToolUseEndEvent(
                tool_use_id="authorized-1",
                tool_name="search",
                arguments={"query": "fresh bounded query"},
            ),
            DoneEvent(
                input_tokens=21,
                output_tokens=5,
                model="agg",
                stop_reason="tool_use",
            ),
        ]

    factories["agg"] = aggregator_events

    def fake_build_provider(cfg: ProviderConfig) -> _FakeProvider:
        return _FakeProvider(cfg, calls, factories)

    monkeypatch.setattr("opensquilla.provider.selector._build_provider", fake_build_provider)
    provider = EnsembleProvider(
        profile_name="test",
        proposers=[_member("p1"), _member("p2")],
        aggregator=_member("agg"),
        record_candidates=True,
        shuffle_candidates=False,
        proposer_tools=True,
        candidate_max_chars=400,
        output_strategy="select_best_candidate",
    )
    tool = ToolDefinition(
        name="search",
        description="Search",
        input_schema=ToolInputSchema(),
    )

    events = [
        event
        async for event in provider.chat(
            [Message(role="user", content="research")],
            tools=[tool],
        )
    ]

    assert [event.kind for event in events] == [
        "provider_heartbeat",
        "provider_heartbeat",
        "provider_heartbeat",
        "tool_use_start",
        "tool_use_delta",
        "tool_use_end",
        "done",
    ]
    assert events[3].tool_use_id == "authorized-1"
    assert events[3].tool_name == "search"
    assert json.loads(events[4].json_fragment) == {"query": "fresh bounded query"}
    assert events[5].arguments == {"query": "fresh bounded query"}
    proposer_calls = [call for call in calls if call["model"] in {"p1", "p2"}]
    assert all(call["tools"] == [tool] for call in proposer_calls)
    aggregator_calls = [call for call in calls if call["model"] == "agg"]
    assert len(aggregator_calls) == 2
    selector_call, reissuer_call = aggregator_calls
    assert selector_call["tools"] is None
    assert reissuer_call["tools"] == [tool]
    assert oversized_query not in str(selector_call["messages"][-1].content)
    assert oversized_query not in str(reissuer_call["messages"][-1].content)
    done = events[-1]
    assert isinstance(done, DoneEvent)
    assert done.stop_reason == "tool_use"
    assert done.ensemble_trace["proposer_tools_enabled"] is True
    assert done.ensemble_trace["selected_candidate_indexes"] == [0]
    assert done.ensemble_trace["final_request_role"] == "candidate_tool_reissuer"
    assert done.ensemble_trace["llm_request_count"] == 4
    assert [request["role"] for request in done.ensemble_trace["requests"]] == [
        "proposer",
        "proposer",
        "candidate_selector",
        "candidate_tool_reissuer",
    ]
    assert [row["role"] for row in done.model_usage_breakdown] == [
        "proposer",
        "proposer",
        "candidate_selector",
        "aggregator",
    ]
    assert done.ensemble_trace["candidate_tool_reissue"] == {
        "required": True,
        "source_candidate_index": 0,
        "proposed_call_count": 1,
        "prompt_truncated": True,
    }
    selected = done.ensemble_trace["candidates"][0]
    assert selected["tool_calls_truncated"] is True
    assert selected["tool_calls"][0]["arguments"]["_truncated"] is True


@pytest.mark.asyncio
async def test_ensemble_select_best_candidate_falls_back_on_unparseable_selector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    def _events(model: str, text: str, in_tokens: int, out_tokens: int):
        return lambda _messages, _tools: [
            TextDeltaEvent(text=text),
            DoneEvent(input_tokens=in_tokens, output_tokens=out_tokens, model=model),
        ]

    factories = {
        "p1": _events("p1", "first draft", 10, 2),
        "p2": _events("p2", "second draft", 11, 3),
        "agg": _events("agg", "not json", 20, 4),
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
        output_strategy="select_best_candidate",
    )

    events = [
        event
        async for event in provider.chat([Message(role="user", content="solve")])
    ]

    assert events[-2].text == "first draft"
    done = events[-1]
    assert isinstance(done, DoneEvent)
    assert done.stop_reason == "selected_candidate"
    assert done.model == "p1"
    assert done.ensemble_trace["selected_candidate_indexes"] == [0]
    selection = done.ensemble_trace["candidate_selection"]
    assert selection["applied"] is False
    assert selection["selected_candidate_index"] == 0
    assert "parseable index" in selection["fallback_reason"]


@pytest.mark.asyncio
async def test_select_best_selector_failure_never_replays_fallback_proposer_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []
    factories: dict[str, Callable[[list[Message], Any], list[Any]]] = {
        "p1": lambda _messages, _tools: [
            ToolUseStartEvent(tool_use_id="proposal-unsafe", tool_name="search"),
            ToolUseDeltaEvent(
                tool_use_id="proposal-unsafe",
                json_fragment='{"query":"unreviewed proposer args"}',
            ),
            ToolUseEndEvent(
                tool_use_id="proposal-unsafe",
                tool_name="search",
                arguments={"query": "unreviewed proposer args"},
            ),
            DoneEvent(input_tokens=10, output_tokens=3, model="p1"),
        ],
        "p2": lambda _messages, _tools: [
            TextDeltaEvent(text="text alternative"),
            DoneEvent(input_tokens=11, output_tokens=2, model="p2"),
        ],
    }

    def aggregator_events(_messages: list[Message], tools: Any) -> list[Any]:
        if tools is None:
            return [
                TextDeltaEvent(text="not json"),
                DoneEvent(input_tokens=20, output_tokens=4, model="agg"),
            ]
        return [
            ToolUseStartEvent(tool_use_id="authorized-safe", tool_name="search"),
            ToolUseDeltaEvent(
                tool_use_id="authorized-safe",
                json_fragment='{"query":"aggregator reviewed"}',
            ),
            ToolUseEndEvent(
                tool_use_id="authorized-safe",
                tool_name="search",
                arguments={"query": "aggregator reviewed"},
            ),
            DoneEvent(input_tokens=21, output_tokens=5, model="agg"),
        ]

    factories["agg"] = aggregator_events

    def fake_build_provider(cfg: ProviderConfig) -> _FakeProvider:
        return _FakeProvider(cfg, calls, factories)

    monkeypatch.setattr("opensquilla.provider.selector._build_provider", fake_build_provider)
    provider = EnsembleProvider(
        profile_name="test",
        proposers=[_member("p1"), _member("p2")],
        aggregator=_member("agg"),
        record_candidates=True,
        shuffle_candidates=False,
        proposer_tools=True,
        output_strategy="select_best_candidate",
    )
    tool = ToolDefinition(
        name="search",
        description="Search",
        input_schema=ToolInputSchema(),
    )

    events = [
        event
        async for event in provider.chat(
            [Message(role="user", content="research")],
            tools=[tool],
        )
    ]

    emitted_starts = [event for event in events if isinstance(event, ToolUseStartEvent)]
    assert [event.tool_use_id for event in emitted_starts] == ["authorized-safe"]
    emitted_ends = [event for event in events if isinstance(event, ToolUseEndEvent)]
    assert emitted_ends[0].arguments == {"query": "aggregator reviewed"}
    done = events[-1]
    assert isinstance(done, DoneEvent)
    selection = done.ensemble_trace["candidate_selection"]
    assert selection["applied"] is False
    assert selection["selected_candidate_index"] == 0
    assert "parseable index" in selection["fallback_reason"]
    assert done.ensemble_trace["final_request_role"] == "candidate_tool_reissuer"
    assert done.ensemble_trace["llm_request_count"] == 4


@pytest.mark.asyncio
async def test_ensemble_prefilters_candidates_with_scorer_before_aggregation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    def _events(model: str, text: str, in_tokens: int, out_tokens: int):
        return lambda _messages, _tools: [
            TextDeltaEvent(text=text),
            DoneEvent(input_tokens=in_tokens, output_tokens=out_tokens, model=model),
        ]

    factories = {
        "p1": _events("p1", "draft from p1", 10, 2),
        "p2": _events("p2", "draft from p2", 11, 3),
        "p3": _events("p3", "draft from p3", 12, 4),
        "p4": _events("p4", "draft from p4", 13, 5),
        "judge": _events(
            "judge",
            (
                '{"selected_candidate_index":3,'
                '"ranked_candidate_indexes":[2,0,1],'
                '"scores":[{"index":2,"score":9.0}]}'
            ),
            20,
            4,
        ),
        "agg": _events("agg", "final fused", 30, 6),
    }

    def fake_build_provider(cfg: ProviderConfig) -> _FakeProvider:
        return _FakeProvider(cfg, calls, factories)

    monkeypatch.setattr("opensquilla.provider.selector._build_provider", fake_build_provider)
    provider = EnsembleProvider(
        profile_name="test",
        proposers=[_member("p1"), _member("p2"), _member("p3"), _member("p4")],
        aggregator=_member("agg"),
        candidate_scorer=_member("judge"),
        candidate_prefilter_top_k=3,
        record_candidates=True,
        shuffle_candidates=False,
    )

    events = [event async for event in provider.chat([Message(role="user", content="solve")])]

    done = events[-1]
    assert isinstance(done, DoneEvent)
    assert done.input_tokens == 96
    assert done.output_tokens == 24
    assert [row["role"] for row in done.model_usage_breakdown] == [
        "proposer",
        "proposer",
        "proposer",
        "proposer",
        "candidate_scorer",
        "aggregator",
    ]
    assert done.ensemble_trace["total_candidates"] == 4
    assert done.ensemble_trace["candidate_prefilter"]["applied"] is True
    assert done.ensemble_trace["candidate_prefilter"]["selected_candidate_indexes"] == [
        2,
        0,
        1,
    ]
    assert done.ensemble_trace["selected_candidate_indexes"] == [2, 0, 1]
    assert done.ensemble_trace["llm_request_count"] == 6
    aggregator_prompt = next(call for call in calls if call["model"] == "agg")[
        "messages"
    ][-1].content
    assert "draft from p1" in aggregator_prompt
    assert "draft from p2" in aggregator_prompt
    assert "draft from p3" in aggregator_prompt
    assert "draft from p4" not in aggregator_prompt


@pytest.mark.asyncio
async def test_ensemble_prefilter_failure_falls_back_to_all_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    def _events(model: str, text: str):
        return lambda _messages, _tools: [
            TextDeltaEvent(text=text),
            DoneEvent(input_tokens=1, output_tokens=1, model=model),
        ]

    factories = {
        "p1": _events("p1", "draft from p1"),
        "p2": _events("p2", "draft from p2"),
        "p3": _events("p3", "draft from p3"),
        "p4": _events("p4", "draft from p4"),
        "judge": _events("judge", "not json"),
        "agg": _events("agg", "final fused"),
    }

    def fake_build_provider(cfg: ProviderConfig) -> _FakeProvider:
        return _FakeProvider(cfg, calls, factories)

    monkeypatch.setattr("opensquilla.provider.selector._build_provider", fake_build_provider)
    provider = EnsembleProvider(
        profile_name="test",
        proposers=[_member("p1"), _member("p2"), _member("p3"), _member("p4")],
        aggregator=_member("agg"),
        candidate_scorer=_member("judge"),
        candidate_prefilter_top_k=3,
        record_candidates=True,
        shuffle_candidates=False,
    )

    events = [event async for event in provider.chat([Message(role="user", content="solve")])]

    done = events[-1]
    assert isinstance(done, DoneEvent)
    assert done.ensemble_trace["candidate_prefilter"]["applied"] is False
    assert done.ensemble_trace["selected_candidate_indexes"] == [0, 1, 2, 3]
    aggregator_prompt = next(call for call in calls if call["model"] == "agg")[
        "messages"
    ][-1].content
    assert "draft from p1" in aggregator_prompt
    assert "draft from p2" in aggregator_prompt
    assert "draft from p3" in aggregator_prompt
    assert "draft from p4" in aggregator_prompt


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
    assert [request["role"] for request in done.ensemble_trace["requests"]] == [
        "proposer",
        "proposer",
        "fallback_single",
    ]
    assert done.ensemble_trace["requests"][-1]["model"] == "fallback-model"
    assert done.ensemble_trace["requests"][-1]["messages"][0]["content"] == "solve"


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
    assert [request["role"] for request in done.ensemble_trace["requests"]] == [
        "proposer",
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
    assert done.ensemble_trace["llm_request_count"] == 3


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
    assert error.diagnostic_done.ensemble_trace["llm_request_count"] == 2
    assert error.diagnostic_done.ensemble_trace["aggregator_error"]["code"] == (
        "ensemble_aggregator_error"
    )
