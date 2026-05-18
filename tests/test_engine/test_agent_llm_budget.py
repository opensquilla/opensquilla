from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import pytest

from opensquilla.engine import (
    Agent,
    AgentConfig,
    AgentState,
    DoneEvent,
    ErrorEvent,
    RunHeartbeatEvent,
    ToolResult,
    WarningEvent,
)
from opensquilla.engine.session_sanitize import session_payload_chars
from opensquilla.provider import (
    ChatConfig,
    Message,
    ProviderHeartbeatEvent,
    ToolDefinition,
    ToolInputSchema,
)
from opensquilla.provider import DoneEvent as ProviderDone
from opensquilla.provider import ErrorEvent as ProviderError
from opensquilla.provider import TextDeltaEvent as ProviderText
from opensquilla.provider import ToolUseEndEvent as ProviderToolUseEnd
from opensquilla.provider import ToolUseStartEvent as ProviderToolUseStart
from opensquilla.session.compaction import CompactionResult


class _StallingProvider:
    provider_name = "fake"

    def __init__(self) -> None:
        self.calls: list[list[Message]] = []
        self.stream_closed = False

    def chat(
        self,
        messages: list[Message],
        tools: list[Any] | None = None,
        config: ChatConfig | None = None,
    ) -> AsyncIterator[Any]:
        self.calls.append(messages)
        return self._stream()

    async def _stream(self) -> AsyncIterator[Any]:
        try:
            await asyncio.sleep(60.0)
            yield ProviderText(text="late")
        finally:
            self.stream_closed = True

    async def list_models(self) -> list[Any]:
        return []


class _ContextOverflowProvider:
    provider_name = "fake"

    def __init__(self, *, success_after: int | None = None) -> None:
        self.success_after = success_after
        self.calls: list[list[Message]] = []

    def chat(
        self,
        messages: list[Message],
        tools: list[Any] | None = None,
        config: ChatConfig | None = None,
    ) -> AsyncIterator[Any]:
        self.calls.append(messages)
        return self._stream(len(self.calls))

    async def _stream(self, call_number: int) -> AsyncIterator[Any]:
        if self.success_after is not None and call_number > self.success_after:
            yield ProviderText(text="ok")
            yield ProviderDone(stop_reason="stop", input_tokens=1, output_tokens=1)
            return
        yield ProviderError(message="context length exceeded", code="400")

    async def list_models(self) -> list[Any]:
        return []


class _ProviderRequestBudgetExceededProvider:
    provider_name = "openrouter"

    def __init__(
        self,
        *,
        success_after: int | None = None,
        proof: dict[str, Any] | None = None,
    ) -> None:
        self.success_after = success_after
        self.proof = proof
        self.calls: list[list[Message]] = []

    def chat(
        self,
        messages: list[Message],
        tools: list[Any] | None = None,
        config: ChatConfig | None = None,
    ) -> AsyncIterator[Any]:
        self.calls.append(messages)
        return self._stream(len(self.calls))

    async def _stream(self, call_number: int) -> AsyncIterator[Any]:
        if self.success_after is not None and call_number > self.success_after:
            yield ProviderText(text="ok")
            yield ProviderDone(stop_reason="stop", input_tokens=1, output_tokens=1)
            return
        message = (
            '{"fallback_reason":"provider_request_budget_exhausted"}'
            if self.proof is None
            else json.dumps(self.proof)
        )
        yield ProviderError(message=message, code="provider_request_budget_exhausted")

    async def list_models(self) -> list[Any]:
        return []


class _ProviderRaisesTimeout:
    provider_name = "fake"

    def __init__(self) -> None:
        self.calls: list[list[Message]] = []

    def chat(
        self,
        messages: list[Message],
        tools: list[Any] | None = None,
        config: ChatConfig | None = None,
    ) -> AsyncIterator[Any]:
        self.calls.append(messages)
        return self._stream()

    async def _stream(self) -> AsyncIterator[Any]:
        raise TimeoutError("provider transport timeout")
        yield ProviderText(text="unreachable")

    async def list_models(self) -> list[Any]:
        return []


class _ProviderHeartbeatThenText:
    provider_name = "fake"

    def chat(
        self,
        messages: list[Message],
        tools: list[Any] | None = None,
        config: ChatConfig | None = None,
    ) -> AsyncIterator[Any]:
        return self._stream()

    async def _stream(self) -> AsyncIterator[Any]:
        yield ProviderHeartbeatEvent(phase="llm_fallback", message="retrying")
        yield ProviderText(text="ok")
        yield ProviderDone(stop_reason="stop", input_tokens=1, output_tokens=1)

    async def list_models(self) -> list[Any]:
        return []


class _ToolUseProvider:
    provider_name = "fake"

    def __init__(self) -> None:
        self.calls: list[list[Message]] = []

    def chat(
        self,
        messages: list[Message],
        tools: list[Any] | None = None,
        config: ChatConfig | None = None,
    ) -> AsyncIterator[Any]:
        self.calls.append(messages)
        return self._stream()

    async def _stream(self) -> AsyncIterator[Any]:
        yield ProviderToolUseStart(tool_use_id="tool-1", tool_name="slow")
        yield ProviderToolUseEnd(
            tool_use_id="tool-1",
            tool_name="slow",
            arguments={},
        )
        yield ProviderDone(stop_reason="tool_use", input_tokens=1, output_tokens=1)

    async def list_models(self) -> list[Any]:
        return []


@pytest.mark.asyncio
async def test_provider_heartbeat_reaches_agent_stream() -> None:
    agent = Agent(
        provider=_ProviderHeartbeatThenText(),
        config=AgentConfig(iteration_timeout=30.0, timeout=60.0, max_provider_retries=0),
    )

    events = [event async for event in agent.run_turn("hello")]

    heartbeat_index = _event_index(
        events,
        lambda event: isinstance(event, RunHeartbeatEvent)
        and event.phase == "llm_fallback"
        and event.message == "retrying",
    )
    text_index = _event_index(
        events,
        lambda event: getattr(event, "kind", None) == "text_delta"
        and getattr(event, "text", None) == "ok",
    )
    assert heartbeat_index < text_index


@pytest.mark.asyncio
async def test_iteration_timeout_interrupts_stalled_provider_stream() -> None:
    provider = _StallingProvider()
    agent = Agent(
        provider=provider,
        config=AgentConfig(iteration_timeout=0.01, max_provider_retries=0),
    )

    events = await asyncio.wait_for(
        _collect_events(agent.run_turn("hello")),
        timeout=0.5,
    )

    error_index = _event_index(
        events,
        lambda event: isinstance(event, ErrorEvent) and event.code == "iteration_timeout",
    )
    state_index = _event_index(
        events,
        lambda event: getattr(event, "kind", None) == "state_change"
        and getattr(event, "to_state", None) == AgentState.ERROR,
    )
    assert state_index < error_index
    assert len(provider.calls) == 1
    assert provider.stream_closed is True
    assert not any(isinstance(event, DoneEvent) for event in events)


@pytest.mark.asyncio
async def test_iteration_timeout_caps_tool_execution() -> None:
    async def slow_tool(call: object) -> ToolResult:
        await asyncio.sleep(0.5)
        return ToolResult(
            tool_use_id=getattr(call, "tool_use_id"),
            tool_name=getattr(call, "tool_name"),
            content="late",
        )

    agent = Agent(
        provider=_ToolUseProvider(),
        config=AgentConfig(
            iteration_timeout=0.05,
            timeout=1.0,
            tool_timeout=5.0,
            max_provider_retries=0,
        ),
        tool_definitions=[
            ToolDefinition(
                name="slow",
                description="Slow tool.",
                input_schema=ToolInputSchema(),
            )
        ],
        tool_handler=slow_tool,
    )

    events = await asyncio.wait_for(_collect_events(agent.run_turn("hello")), timeout=0.25)

    assert any(
        isinstance(event, ErrorEvent) and event.code == "iteration_timeout"
        for event in events
    )


@pytest.mark.asyncio
async def test_provider_timeout_error_is_not_reclassified_as_iteration_timeout() -> None:
    provider = _ProviderRaisesTimeout()
    agent = Agent(
        provider=provider,
        config=AgentConfig(iteration_timeout=30.0, timeout=60.0, max_provider_retries=0),
    )

    events = [event async for event in agent.run_turn("hello")]

    assert len(provider.calls) == 1
    assert any(
        isinstance(event, ErrorEvent) and event.code == "agent_runtime_timeout"
        for event in events
    )
    assert not any(
        isinstance(event, ErrorEvent) and event.code == "iteration_timeout"
        for event in events
    )


@pytest.mark.asyncio
async def test_context_overflow_noop_compaction_does_not_resend_unchanged_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _noop_compact(request: Any) -> CompactionResult:
        return CompactionResult(
            summary="",
            kept_entries=request.entries,
            removed_count=0,
            chunks_processed=0,
        )

    monkeypatch.setattr("opensquilla.engine.agent.compact_context", _noop_compact)
    provider = _ContextOverflowProvider()
    agent = Agent(
        provider=provider,
        config=AgentConfig(
            max_provider_retries=0,
            max_overflow_retries=2,
            flush_enabled=False,
        ),
    )

    events = [event async for event in agent.run_turn("hello")]

    assert len(provider.calls) == 1
    assert any(
        isinstance(event, ErrorEvent) and event.code == "compaction_not_smaller"
        for event in events
    )
    assert not any(getattr(event, "kind", None) == "compaction" for event in events)


@pytest.mark.asyncio
async def test_context_overflow_summary_only_larger_payload_does_not_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _summary_only_compact(request: Any) -> CompactionResult:
        return CompactionResult(
            summary="summary without reducing request payload",
            kept_entries=request.entries,
            removed_count=0,
            chunks_processed=1,
        )

    monkeypatch.setattr("opensquilla.engine.agent.compact_context", _summary_only_compact)
    provider = _ContextOverflowProvider()
    agent = Agent(
        provider=provider,
        config=AgentConfig(
            max_provider_retries=0,
            max_overflow_retries=2,
            flush_enabled=False,
        ),
    )

    events = [event async for event in agent.run_turn("hello")]

    assert len(provider.calls) == 1
    assert any(
        isinstance(event, ErrorEvent) and event.code == "compaction_not_smaller"
        for event in events
    )
    assert not any(getattr(event, "kind", None) == "compaction" for event in events)


@pytest.mark.asyncio
async def test_context_overflow_effective_compaction_allows_single_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _effective_compact(request: Any) -> CompactionResult:
        return CompactionResult(
            summary="short summary",
            kept_entries=[],
            removed_count=len(request.entries),
            chunks_processed=1,
        )

    monkeypatch.setattr("opensquilla.engine.agent.compact_context", _effective_compact)
    provider = _ContextOverflowProvider(success_after=1)
    agent = Agent(
        provider=provider,
        config=AgentConfig(
            max_provider_retries=0,
            max_overflow_retries=2,
            flush_enabled=False,
        ),
    )

    events = [event async for event in agent.run_turn("x" * 4000)]

    assert len(provider.calls) == 2
    assert _provider_payload_is_smaller(provider.calls[0], provider.calls[1])
    assert any(event.kind == "done" and getattr(event, "text", "") == "ok" for event in events)


@pytest.mark.asyncio
async def test_provider_request_budget_exhausted_compacts_warns_and_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _effective_compact(request: Any) -> CompactionResult:
        return CompactionResult(
            summary="short summary",
            kept_entries=[],
            removed_count=len(request.entries),
            chunks_processed=1,
        )

    monkeypatch.setattr("opensquilla.engine.agent.compact_context", _effective_compact)
    provider = _ProviderRequestBudgetExceededProvider(success_after=1)
    agent = Agent(
        provider=provider,
        config=AgentConfig(
            max_provider_retries=0,
            max_overflow_retries=2,
            flush_enabled=False,
        ),
    )

    events = [event async for event in agent.run_turn("x" * 4000)]
    warning_codes = [
        event.code for event in events if isinstance(event, WarningEvent)
    ]

    assert len(provider.calls) == 2
    assert _provider_payload_is_smaller(provider.calls[0], provider.calls[1])
    assert warning_codes == [
        "context_auto_compaction_start",
        "context_auto_compaction_retry",
    ]
    assert any(event.kind == "done" and getattr(event, "text", "") == "ok" for event in events)
    assert not any(
        isinstance(event, ErrorEvent)
        and event.code == "provider_request_budget_exhausted"
        for event in events
    )


@pytest.mark.asyncio
async def test_provider_request_budget_recent_tail_exhaustion_is_reported_precisely(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _effective_compact(request: Any) -> CompactionResult:
        return CompactionResult(
            summary="short summary",
            kept_entries=[],
            removed_count=len(request.entries),
            chunks_processed=1,
        )

    monkeypatch.setattr("opensquilla.engine.agent.compact_context", _effective_compact)
    provider = _ProviderRequestBudgetExceededProvider(
        proof={
            "fallback_reason": "provider_request_budget_exhausted",
            "recent_tail_too_large": True,
            "estimated_chars": 100_000,
            "proof_budget": 96_000,
        }
    )
    agent = Agent(
        provider=provider,
        config=AgentConfig(
            max_provider_retries=0,
            max_overflow_retries=1,
            flush_enabled=False,
        ),
    )

    events = [event async for event in agent.run_turn("x" * 4000)]
    errors = [event for event in events if isinstance(event, ErrorEvent)]

    assert len(provider.calls) == 2
    assert errors[-1].code == "current_turn_context_exhausted"
    assert "current turn" in errors[-1].message


@pytest.mark.asyncio
async def test_context_overflow_degraded_flush_still_runs_live_compaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compact_called = False

    async def _compact_runs_after_degraded_flush(request: Any) -> CompactionResult:
        nonlocal compact_called
        compact_called = True
        return CompactionResult(
            summary="short summary",
            kept_entries=[],
            removed_count=len(request.entries),
            chunks_processed=1,
        )

    monkeypatch.setattr(
        "opensquilla.engine.agent.compact_context",
        _compact_runs_after_degraded_flush,
    )
    provider = _ContextOverflowProvider(success_after=1)
    agent = Agent(
        provider=provider,
        config=AgentConfig(max_provider_retries=0, max_overflow_retries=2),
    )

    events = [event async for event in agent.run_turn("x" * 4000)]

    assert compact_called is True
    assert len(provider.calls) == 2
    assert any(event.kind == "done" and getattr(event, "text", "") == "ok" for event in events)
    assert not any(
        isinstance(event, ErrorEvent)
        and event.code in {"compaction_refused_memory_flush", "compaction_refused_flush_timeout"}
        for event in events
    )


@pytest.mark.asyncio
async def test_context_overflow_flush_timeout_records_backoff_and_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _compact_runs_after_flush_timeout(request: Any) -> CompactionResult:
        return CompactionResult(
            summary="short summary",
            kept_entries=[],
            removed_count=len(request.entries),
            chunks_processed=1,
        )

    monkeypatch.setattr(
        "opensquilla.engine.agent.compact_context",
        _compact_runs_after_flush_timeout,
    )
    provider = _ContextOverflowProvider(success_after=1)
    agent = Agent(
        provider=provider,
        config=AgentConfig(
            max_provider_retries=0,
            max_overflow_retries=2,
            flush_timeout_seconds=0.01,
            flush_backoff_initial_seconds=10.0,
        ),
    )

    async def slow_flush(_plan: Any, _messages: Any) -> None:
        await asyncio.sleep(1.0)

    monkeypatch.setattr(agent, "_run_flush", slow_flush)
    try:
        events = [event async for event in agent.run_turn("x" * 4000)]
    finally:
        task = agent._active_flush_task
        if task is not None and not task.done():
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    assert len(provider.calls) == 2
    assert agent._flush_backoff_seconds == 10.0
    assert any(event.kind == "done" and getattr(event, "text", "") == "ok" for event in events)
    assert not any(
        isinstance(event, ErrorEvent)
        and event.code in {"compaction_refused_memory_flush", "compaction_refused_flush_timeout"}
        for event in events
    )


async def _collect_events(stream: AsyncIterator[Any]) -> list[Any]:
    return [event async for event in stream]


def _event_index(events: list[Any], predicate: Any) -> int:
    return next(index for index, event in enumerate(events) if predicate(event))


def _provider_payload_is_smaller(before: list[Message], after: list[Message]) -> bool:
    return len(after) < len(before) or session_payload_chars(after) < session_payload_chars(before)
