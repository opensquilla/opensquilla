from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest
import structlog.testing

from opensquilla.engine import Agent, AgentConfig, ThinkingLevel, ToolResult
from opensquilla.engine.runtime import TurnRunner
from opensquilla.engine.usage import UsageTracker
from opensquilla.provider import (
    ChatConfig,
    Message,
    ModelCapabilities,
    ToolDefinition,
    ToolInputSchema,
)
from opensquilla.provider import DoneEvent as ProviderDone
from opensquilla.provider import TextDeltaEvent as ProviderText
from opensquilla.provider import ToolUseEndEvent as ProviderToolUseEnd
from opensquilla.provider import ToolUseStartEvent as ProviderToolUseStart
from opensquilla.session.manager import SessionManager
from opensquilla.session.storage import SessionStorage
from opensquilla.tools.types import CallerKind, ToolContext


class _SequenceProvider:
    provider_name = "fake"

    def __init__(self, streams: list[list[Any]]) -> None:
        self.streams = streams
        self.calls: list[dict[str, Any]] = []

    def chat(
        self,
        messages: list[Message],
        tools: list[Any] | None = None,
        config: ChatConfig | None = None,
    ) -> AsyncIterator[Any]:
        index = len(self.calls)
        self.calls.append({"messages": messages, "tools": tools, "config": config})
        events = self.streams[index] if index < len(self.streams) else self.streams[-1]
        return self._stream(events)

    async def _stream(self, events: list[Any]) -> AsyncIterator[Any]:
        for event in events:
            yield event

    async def list_models(self) -> list[Any]:
        return []


class _FallbackSequenceProvider(_SequenceProvider):
    def __init__(self, streams: list[list[Any]]) -> None:
        super().__init__(streams)
        self.fallback_reasons: list[str] = []

    def fallback_after_invalid_response(self, reason: str) -> bool:
        self.fallback_reasons.append(reason)
        return True


def _large_reasoning_only_done() -> ProviderDone:
    return ProviderDone(
        stop_reason="stop",
        input_tokens=35_000,
        output_tokens=2,
        reasoning_tokens=2,
        reasoning_content="internal",
    )


class _SelectorClone:
    def __init__(self, provider: _SequenceProvider) -> None:
        self.provider = provider
        self.current_config = SimpleNamespace(model="fake-model")

    def resolve(self) -> _SequenceProvider:
        return self.provider

    def override_model(self, model: str) -> None:
        self.current_config.model = model

    def next_fallback_after_failure(self, primary_failure: Exception) -> _SequenceProvider:
        raise IndexError("No fallback configured")


class _ProviderSelector:
    def __init__(self, provider: _SequenceProvider) -> None:
        self.provider = provider

    def clone(self) -> _SelectorClone:
        return _SelectorClone(self.provider)


class _CacheReport:
    break_detected = False

    def to_log_dict(self) -> dict[str, Any]:
        return {}


@pytest.mark.asyncio
async def test_final_done_returns_openrouter_deepseek_reasoning_content() -> None:
    provider = _SequenceProvider(
        [
            [
                ProviderText(text="ok"),
                ProviderDone(
                    stop_reason="stop",
                    input_tokens=10,
                    output_tokens=1,
                    reasoning_tokens=4,
                    reasoning_content="I reasoned through the OpenRouter response.",
                    model="deepseek/deepseek-v4-flash",
                ),
            ]
        ]
    )
    agent = Agent(
        provider=provider,
        config=AgentConfig(
            thinking=ThinkingLevel.HIGH,
            model_id="deepseek/deepseek-v4-flash",
            model_capabilities=ModelCapabilities(
                supports_reasoning=True,
                supports_tools=True,
                reasoning_format="openrouter",
            ),
        ),
    )

    events = [event async for event in agent.run_turn("hello")]

    done = next(event for event in events if event.kind == "done")
    assert done.text == "ok"
    assert done.reasoning_content == "I reasoned through the OpenRouter response."


@pytest.mark.asyncio
async def test_reasoning_only_first_turn_retries_with_thinking_disabled() -> None:
    provider = _SequenceProvider(
        [
            [
                ProviderDone(
                    stop_reason="stop",
                    input_tokens=10,
                    output_tokens=5,
                    reasoning_tokens=5,
                    reasoning_content="internal reasoning",
                    model="z-ai/glm-5.1-20260406",
                )
            ],
            [
                ProviderText(text="ok"),
                ProviderDone(
                    stop_reason="stop",
                    input_tokens=11,
                    output_tokens=1,
                    model="z-ai/glm-5.1-20260406",
                ),
            ],
        ]
    )
    usage = UsageTracker()
    agent = Agent(
        provider=provider,
        config=AgentConfig(
            thinking=ThinkingLevel.MEDIUM,
            retry_base_backoff_ms=0,
            retry_max_backoff_ms=0,
        ),
        usage_tracker=usage,
        session_key="agent:test:reasoning-only",
    )

    events = [event async for event in agent.run_turn("hello")]

    assert [event.kind for event in events if event.kind == "error"] == []
    assert any(
        event.kind == "warning" and event.code == "provider_reasoning_only_retry"
        for event in events
    )
    done = next(event for event in events if event.kind == "done")
    assert done.text == "ok"
    assert done.input_tokens == 21
    assert done.output_tokens == 6
    assert done.reasoning_tokens == 5
    assert len(provider.calls) == 2
    assert provider.calls[0]["config"].thinking is True
    assert provider.calls[1]["config"].thinking is False
    assert provider.calls[1]["config"].thinking_level is None
    assert provider.calls[1]["config"].thinking_budget_tokens == 0
    tracked = usage.get("agent:test:reasoning-only")
    assert tracked is not None
    assert tracked.input_tokens == 21
    assert tracked.output_tokens == 6
    assistant_messages = [msg for msg in agent._history if msg.role == "assistant"]
    assert len(assistant_messages) == 1
    assert assistant_messages[0].content[0].text == "ok"
    assert assistant_messages[0].reasoning_content is None


@pytest.mark.asyncio
async def test_reasoning_only_post_tool_turn_retries_with_thinking_disabled() -> None:
    provider = _SequenceProvider(
        [
            [
                ProviderToolUseStart(tool_use_id="tool-1", tool_name="echo"),
                ProviderToolUseEnd(
                    tool_use_id="tool-1",
                    tool_name="echo",
                    arguments={"value": "ok"},
                ),
                ProviderDone(stop_reason="tool_use", input_tokens=3, output_tokens=1),
            ],
            [
                ProviderDone(
                    stop_reason="stop",
                    input_tokens=4,
                    output_tokens=2,
                    reasoning_tokens=2,
                    reasoning_content="internal reasoning",
                )
            ],
            [
                ProviderText(text="done"),
                ProviderDone(stop_reason="stop", input_tokens=5, output_tokens=1),
            ],
        ]
    )

    async def tool_handler(call: Any) -> ToolResult:
        return ToolResult(
            tool_use_id=call.tool_use_id,
            tool_name=call.tool_name,
            content="tool ok",
        )

    agent = Agent(
        provider=provider,
        config=AgentConfig(
            thinking=ThinkingLevel.MEDIUM,
            max_iterations=2,
            retry_base_backoff_ms=0,
            retry_max_backoff_ms=0,
        ),
        tool_definitions=[
            ToolDefinition(
                name="echo",
                description="Echo.",
                input_schema=ToolInputSchema(
                    properties={"value": {"type": "string"}},
                    required=["value"],
                ),
            )
        ],
        tool_handler=tool_handler,
    )

    events = [event async for event in agent.run_turn("hello")]

    assert any(event.kind == "done" and event.text == "done" for event in events)
    assert any(
        event.kind == "warning" and event.code == "provider_reasoning_only_retry"
        for event in events
    )
    assert len(provider.calls) == 3
    assert provider.calls[1]["config"].thinking is True
    assert provider.calls[2]["config"].thinking is False


@pytest.mark.asyncio
async def test_reasoning_only_with_thinking_disabled_surfaces_empty_response() -> None:
    provider = _SequenceProvider(
        [
            [
                ProviderDone(
                    stop_reason="stop",
                    input_tokens=4,
                    output_tokens=2,
                    reasoning_tokens=2,
                    reasoning_content="internal reasoning",
                )
            ]
        ]
    )
    agent = Agent(
        provider=provider,
        config=AgentConfig(thinking=False, retry_base_backoff_ms=0, retry_max_backoff_ms=0),
    )

    events = [event async for event in agent.run_turn("hello")]

    assert len(provider.calls) == 1
    assert any(event.kind == "error" and event.code == "empty_response" for event in events)
    done = next(event for event in events if event.kind == "done")
    assert done.input_tokens == 4
    assert done.output_tokens == 2
    assert done.reasoning_tokens == 2


@pytest.mark.asyncio
async def test_clean_empty_done_retries_once_then_errors() -> None:
    provider = _SequenceProvider(
        [
            [ProviderDone(stop_reason="stop", input_tokens=3, output_tokens=0)],
            [ProviderDone(stop_reason="stop", input_tokens=4, output_tokens=0)],
        ]
    )
    agent = Agent(
        provider=provider,
        config=AgentConfig(
            max_provider_retries=1,
            retry_base_backoff_ms=0,
            retry_max_backoff_ms=0,
        ),
    )

    events = [event async for event in agent.run_turn("hello")]

    assert len(provider.calls) == 2
    assert any(event.kind == "warning" and event.code == "provider_empty_retry" for event in events)
    assert any(event.kind == "error" and event.code == "empty_response" for event in events)
    done = next(event for event in events if event.kind == "done")
    assert done.input_tokens == 7
    assert done.output_tokens == 0


@pytest.mark.asyncio
async def test_clean_empty_done_can_switch_to_selector_fallback() -> None:
    provider = _FallbackSequenceProvider(
        [
            [ProviderDone(stop_reason="stop", input_tokens=3, output_tokens=0)],
            [
                ProviderText(text="ok"),
                ProviderDone(stop_reason="stop", input_tokens=4, output_tokens=1),
            ],
        ]
    )
    agent = Agent(
        provider=provider,
        config=AgentConfig(max_provider_retries=0),
    )

    events = [event async for event in agent.run_turn("hello")]

    assert provider.fallback_reasons == ["malformed_empty"]
    assert len(provider.calls) == 2
    assert any(event.kind == "done" and event.text == "ok" for event in events)
    assert not any(event.kind == "error" for event in events)


@pytest.mark.asyncio
async def test_large_reasoning_only_uses_fallback_before_same_model_retry() -> None:
    provider = _FallbackSequenceProvider(
        [
            [_large_reasoning_only_done()],
            [
                ProviderText(text="ok"),
                ProviderDone(stop_reason="stop", input_tokens=4, output_tokens=1),
            ],
        ]
    )
    agent = Agent(
        provider=provider,
        config=AgentConfig(
            thinking=ThinkingLevel.MEDIUM,
            retry_base_backoff_ms=0,
            retry_max_backoff_ms=0,
        ),
    )

    events = [event async for event in agent.run_turn("hello")]

    assert provider.fallback_reasons == ["reasoning_only"]
    assert len(provider.calls) == 2
    assert not any(
        event.kind == "warning" and event.code == "provider_reasoning_only_retry"
        for event in events
    )
    assert any(
        event.kind == "warning" and event.code == "provider_large_context_fallback"
        for event in events
    )
    assert any(event.kind == "done" and event.text == "ok" for event in events)


@pytest.mark.asyncio
async def test_large_empty_response_without_fallback_surfaces_clear_error() -> None:
    provider = _SequenceProvider(
        [[ProviderDone(stop_reason="stop", input_tokens=35_000, output_tokens=0)]]
    )
    agent = Agent(
        provider=provider,
        config=AgentConfig(
            max_provider_retries=1,
            retry_base_backoff_ms=0,
            retry_max_backoff_ms=0,
        ),
    )

    events = [event async for event in agent.run_turn("hello")]

    assert len(provider.calls) == 1
    error = next(event for event in events if event.kind == "error")
    assert error.code == "empty_response"
    assert "large input" in error.message
    assert "attachment" in error.message
    assert "summarize" in error.message or "shorten" in error.message
    assert "stronger model" in error.message
    assert not any(
        event.kind == "warning" and event.code == "provider_empty_retry"
        for event in events
    )


@pytest.mark.asyncio
async def test_incomplete_tool_stream_errors_without_running_tool() -> None:
    provider = _SequenceProvider(
        [
            [
                ProviderToolUseStart(tool_use_id="tool-1", tool_name="echo"),
                ProviderDone(stop_reason="tool_use", input_tokens=5, output_tokens=1),
            ]
        ]
    )
    called = False

    async def tool_handler(call: Any) -> ToolResult:
        nonlocal called
        called = True
        return ToolResult(tool_use_id=call.tool_use_id, tool_name=call.tool_name, content="tool ok")

    agent = Agent(
        provider=provider,
        config=AgentConfig(retry_base_backoff_ms=0, retry_max_backoff_ms=0),
        tool_definitions=[
            ToolDefinition(
                name="echo",
                description="Echo.",
                input_schema=ToolInputSchema(),
            )
        ],
        tool_handler=tool_handler,
    )

    events = [event async for event in agent.run_turn("hello")]

    assert called is False
    assert any(event.kind == "tool_use_start" for event in events)
    assert any(event.kind == "error" and event.code == "incomplete_tool_stream" for event in events)
    done = next(event for event in events if event.kind == "done")
    assert done.input_tokens == 5
    assert done.output_tokens == 1
    assert agent._history == []


@pytest.mark.asyncio
async def test_turn_runner_drops_unpaired_tool_use_from_incomplete_stream_transcript() -> None:
    storage = SessionStorage(":memory:")
    await storage.connect()
    manager = SessionManager(storage)
    session_key = "agent:main:incomplete-tool-stream"
    await manager.create(session_key)
    provider = _SequenceProvider(
        [
            [
                ProviderToolUseStart(tool_use_id="tool-1", tool_name="echo"),
                ProviderDone(stop_reason="tool_use", input_tokens=5, output_tokens=1),
            ]
        ]
    )
    runner = TurnRunner(
        provider_selector=_ProviderSelector(provider),
        session_manager=manager,
    )

    try:
        events = [
            event
            async for event in runner.run(
                "hello",
                session_key,
                ToolContext(is_owner=True, caller_kind=CallerKind.CLI),
                history_has_persisted_user=False,
                no_memory_capture=True,
            )
        ]
        transcript = await manager.get_transcript(session_key)
    finally:
        await storage.close()

    assert any(event.kind == "error" and event.code == "incomplete_tool_stream" for event in events)
    assert all(entry.role != "assistant" for entry in transcript)
    assert any(
        entry.role == "system"
        and "Provider stream ended with an incomplete tool call" in entry.content
        for entry in transcript
    )


@pytest.mark.asyncio
async def test_turn_runner_persists_no_provider_error_to_transcript() -> None:
    storage = SessionStorage(":memory:")
    await storage.connect()
    manager = SessionManager(storage)
    session_key = "agent:main:no-provider"
    await manager.create(session_key)
    runner = TurnRunner(
        provider_selector=_ProviderSelector(None),  # type: ignore[arg-type]
        session_manager=manager,
    )

    try:
        events = [
            event
            async for event in runner.run(
                "hello",
                session_key,
                ToolContext(is_owner=True, caller_kind=CallerKind.CLI),
                history_has_persisted_user=False,
                no_memory_capture=True,
            )
        ]
        transcript = await manager.get_transcript(session_key)
    finally:
        await storage.close()

    assert any(event.kind == "error" and event.code == "no_provider" for event in events)
    assert any(
        entry.role == "system" and entry.content == "Error: No provider available"
        for entry in transcript
    )


@pytest.mark.asyncio
async def test_no_done_without_visible_output_retries_once_then_errors() -> None:
    provider = _SequenceProvider([[], []])
    agent = Agent(
        provider=provider,
        config=AgentConfig(
            max_provider_retries=1,
            retry_base_backoff_ms=0,
            retry_max_backoff_ms=0,
        ),
    )

    events = [event async for event in agent.run_turn("hello")]

    assert len(provider.calls) == 2
    assert any(
        event.kind == "error" and event.code == "provider_stream_incomplete"
        for event in events
    )
    assert not any(event.kind == "done" for event in events)


@pytest.mark.asyncio
async def test_no_done_after_text_does_not_retry() -> None:
    provider = _SequenceProvider([[ProviderText(text="partial")]])
    agent = Agent(
        provider=provider,
        config=AgentConfig(
            max_provider_retries=1,
            retry_base_backoff_ms=0,
            retry_max_backoff_ms=0,
        ),
    )

    events = [event async for event in agent.run_turn("hello")]

    assert len(provider.calls) == 1
    assert any(event.kind == "text_delta" and event.text == "partial" for event in events)
    assert any(
        event.kind == "error" and event.code == "provider_stream_incomplete"
        for event in events
    )
    assert not any(event.kind == "done" for event in events)


@pytest.mark.asyncio
async def test_length_capped_visible_text_continues_once_before_terminal() -> None:
    provider = _SequenceProvider(
        [
            [
                ProviderText(text="partial answer"),
                ProviderDone(stop_reason="length", input_tokens=7, output_tokens=9),
            ],
            [
                ProviderText(text=" finished"),
                ProviderDone(stop_reason="stop", input_tokens=8, output_tokens=1),
            ],
        ]
    )
    agent = Agent(
        provider=provider,
        config=AgentConfig(
            max_provider_retries=1,
            retry_base_backoff_ms=0,
            retry_max_backoff_ms=0,
        ),
    )

    events = [event async for event in agent.run_turn("hello")]

    assert len(provider.calls) == 2
    assert any(event.kind == "text_delta" and event.text == "partial answer" for event in events)
    assert any(event.kind == "text_delta" and event.text == " finished" for event in events)
    assert any(
        event.kind == "warning" and event.code == "provider_output_continue"
        for event in events
    )
    assert not any(event.kind == "error" for event in events)
    done = next(event for event in events if event.kind == "done")
    assert done.text == "partial answer finished"
    assert done.input_tokens == 15
    assert done.output_tokens == 10


@pytest.mark.asyncio
async def test_length_capped_visible_text_uses_configured_continuation_budget() -> None:
    provider = _SequenceProvider(
        [
            [
                ProviderText(text="part one "),
                ProviderDone(stop_reason="length", input_tokens=1, output_tokens=2),
            ],
            [
                ProviderText(text="part two "),
                ProviderDone(stop_reason="length", input_tokens=3, output_tokens=4),
            ],
            [
                ProviderText(text="part three "),
                ProviderDone(stop_reason="length", input_tokens=5, output_tokens=6),
            ],
            [
                ProviderText(text="done"),
                ProviderDone(stop_reason="stop", input_tokens=7, output_tokens=8),
            ],
        ]
    )
    agent = Agent(
        provider=provider,
        config=AgentConfig(
            length_capped_continuations=3,
            retry_base_backoff_ms=0,
            retry_max_backoff_ms=0,
        ),
    )

    events = [event async for event in agent.run_turn("hello")]

    assert len(provider.calls) == 4
    assert sum(
        1
        for event in events
        if event.kind == "warning" and event.code == "provider_output_continue"
    ) == 3
    assert not any(event.kind == "error" for event in events)
    done = next(event for event in events if event.kind == "done")
    assert done.text == "part one part two part three done"
    assert done.input_tokens == 16
    assert done.output_tokens == 20


@pytest.mark.asyncio
async def test_length_capped_exhaustion_records_partial_diagnostics() -> None:
    provider = _SequenceProvider(
        [
            [
                ProviderText(text="first partial "),
                ProviderDone(stop_reason="length", input_tokens=1, output_tokens=2),
            ],
            [
                ProviderText(text="second partial "),
                ProviderDone(stop_reason="length", input_tokens=3, output_tokens=4),
            ],
        ]
    )
    agent = Agent(
        provider=provider,
        config=AgentConfig(
            length_capped_continuations=1,
            retry_base_backoff_ms=0,
            retry_max_backoff_ms=0,
        ),
    )

    with structlog.testing.capture_logs() as captured:
        events = [event async for event in agent.run_turn("hello")]

    assert len(provider.calls) == 2
    assert any(event.kind == "text_delta" and event.text == "first partial " for event in events)
    assert any(event.kind == "text_delta" and event.text == "second partial " for event in events)
    assert any(
        event.kind == "warning" and event.code == "provider_output_continue"
        for event in events
    )
    assert any(
        event.kind == "error" and event.code == "provider_output_truncated"
        for event in events
    )
    exhausted = [
        event
        for event in captured
        if event.get("event") == "provider.output_truncated_exhausted"
    ]
    assert exhausted
    assert exhausted[-1]["attempt"] == 1
    assert exhausted[-1]["budget"] == 1
    assert exhausted[-1]["visible_chars"] == len("second partial ")
    assert exhausted[-1]["partial_preserved"] is True


@pytest.mark.asyncio
async def test_length_capped_tool_call_is_not_executed() -> None:
    provider = _SequenceProvider(
        [
            [
                ProviderToolUseStart(tool_use_id="tool-1", tool_name="echo"),
                ProviderToolUseEnd(
                    tool_use_id="tool-1",
                    tool_name="echo",
                    arguments={"value": "x"},
                ),
                ProviderDone(stop_reason="length", input_tokens=7, output_tokens=9),
            ]
        ]
    )
    called = False

    async def tool_handler(call: Any) -> ToolResult:
        nonlocal called
        called = True
        return ToolResult(tool_use_id=call.tool_use_id, tool_name=call.tool_name, content="tool ok")

    agent = Agent(
        provider=provider,
        config=AgentConfig(retry_base_backoff_ms=0, retry_max_backoff_ms=0),
        tool_definitions=[
            ToolDefinition(
                name="echo",
                description="Echo.",
                input_schema=ToolInputSchema(),
            )
        ],
        tool_handler=tool_handler,
    )

    events = [event async for event in agent.run_turn("hello")]

    assert called is False
    assert any(event.kind == "tool_use_start" for event in events)
    assert any(
        event.kind == "error" and event.code == "provider_output_truncated"
        for event in events
    )
    assert not any(event.kind == "tool_result" for event in events)
    assert agent._history == []


@pytest.mark.asyncio
async def test_discarded_empty_attempt_counts_usage_but_skips_cache_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _SequenceProvider(
        [
            [ProviderDone(stop_reason="stop", input_tokens=3, output_tokens=0)],
            [
                ProviderText(text="ok"),
                ProviderDone(stop_reason="stop", input_tokens=4, output_tokens=1),
            ],
        ]
    )
    cache_checks: list[Any] = []

    def fake_cache_check(*args: Any, **kwargs: Any) -> _CacheReport:
        cache_checks.append((args, kwargs))
        return _CacheReport()

    monkeypatch.setattr("opensquilla.engine.agent.check_response_for_cache_break", fake_cache_check)
    usage = UsageTracker()
    agent = Agent(
        provider=provider,
        config=AgentConfig(
            max_provider_retries=1,
            retry_base_backoff_ms=0,
            retry_max_backoff_ms=0,
        ),
        usage_tracker=usage,
        session_key="agent:test:empty-retry",
    )

    events = [event async for event in agent.run_turn("hello")]

    done = next(event for event in events if event.kind == "done")
    assert done.input_tokens == 7
    assert done.output_tokens == 1
    tracked = usage.get("agent:test:empty-retry")
    assert tracked is not None
    assert tracked.input_tokens == 7
    assert tracked.output_tokens == 1
    assert len(cache_checks) == 1
    assert len([msg for msg in agent._history if msg.role == "assistant"]) == 1
