from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest

from opensquilla.engine import Agent, AgentConfig, ToolResult
from opensquilla.engine.subagent import SubagentSpec
from opensquilla.engine.types import ArtifactEvent, ErrorEvent
from opensquilla.engine.usage import UsageTracker
from opensquilla.provider import (
    ChatConfig,
    Message,
    ToolDefinition,
    ToolInputSchema,
)
from opensquilla.provider import (
    DoneEvent as ProviderDone,
)
from opensquilla.provider import (
    ErrorEvent as ProviderError,
)
from opensquilla.provider import (
    TextDeltaEvent as ProviderText,
)
from opensquilla.provider import (
    ToolUseEndEvent as ProviderToolUseEnd,
)
from opensquilla.provider import (
    ToolUseStartEvent as ProviderToolUseStart,
)


class _LoopingToolProvider:
    provider_name = "fake"

    def __init__(self, *, final_on_call: int | None = None) -> None:
        self.final_on_call = final_on_call
        self.calls: list[list[Message]] = []

    def chat(
        self,
        messages: list[Message],
        tools: list[Any] | None = None,
        config: ChatConfig | None = None,
    ) -> AsyncIterator[Any]:
        self.calls.append(messages)
        call_number = len(self.calls)
        return self._stream(call_number)

    async def _stream(self, call_number: int) -> AsyncIterator[Any]:
        if self.final_on_call == call_number:
            yield ProviderText(text="done")
            yield ProviderDone(stop_reason="stop", input_tokens=1, output_tokens=1)
            return

        tool_id = f"tool-{call_number}"
        yield ProviderToolUseStart(tool_use_id=tool_id, tool_name="echo")
        yield ProviderToolUseEnd(
            tool_use_id=tool_id,
            tool_name="echo",
            arguments={"value": "again"},
        )
        yield ProviderDone(stop_reason="tool_use", input_tokens=1, output_tokens=1)

    async def list_models(self) -> list[Any]:
        return []




class _ToolThenProviderErrorProvider:
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
        call_number = len(self.calls)
        return self._stream(call_number)

    async def _stream(self, call_number: int) -> AsyncIterator[Any]:
        if call_number == 1:
            yield ProviderToolUseStart(tool_use_id="tool-1", tool_name="echo")
            yield ProviderToolUseEnd(
                tool_use_id="tool-1",
                tool_name="echo",
                arguments={"value": "again"},
            )
            yield ProviderDone(stop_reason="tool_use", input_tokens=1, output_tokens=1)
            return
        yield ProviderError(message="request timed out", code="request_error")

    async def list_models(self) -> list[Any]:
        return []

class _DoneUsageProvider:
    provider_name = "fake"

    def __init__(
        self,
        *,
        input_tokens: int = 1,
        output_tokens: int = 1,
        billed_cost: float = 0.0,
    ) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.billed_cost = billed_cost
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
        yield ProviderText(text="done")
        yield ProviderDone(
            stop_reason="stop",
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            billed_cost=self.billed_cost,
        )

    async def list_models(self) -> list[Any]:
        return []


class _ArtifactThenProviderErrorProvider:
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
        call_number = len(self.calls)
        return self._stream(call_number)

    async def _stream(self, call_number: int) -> AsyncIterator[Any]:
        if call_number == 1:
            tool_id = "publish-1"
            yield ProviderToolUseStart(
                tool_use_id=tool_id,
                tool_name="publish_artifact",
            )
            yield ProviderToolUseEnd(
                tool_use_id=tool_id,
                tool_name="publish_artifact",
                arguments={"path": "report.txt"},
            )
            yield ProviderDone(stop_reason="tool_use", input_tokens=1, output_tokens=1)
            return

        yield ProviderError(message="request timed out", code="request_error")

    async def list_models(self) -> list[Any]:
        return []


async def _echo_tool(call: Any) -> ToolResult:
    return ToolResult(
        tool_use_id=call.tool_use_id,
        tool_name=call.tool_name,
        content="ok",
    )


async def _error_tool(call: Any) -> ToolResult:
    return ToolResult(
        tool_use_id=call.tool_use_id,
        tool_name=call.tool_name,
        content="invalid arguments",
        is_error=True,
    )


def _echo_definition() -> ToolDefinition:
    return ToolDefinition(
        name="echo",
        description="Echo.",
        input_schema=ToolInputSchema(
            properties={"value": {"type": "string"}},
            required=["value"],
        ),
    )


def _publish_artifact_definition() -> ToolDefinition:
    return ToolDefinition(
        name="publish_artifact",
        description="Publish an artifact.",
        input_schema=ToolInputSchema(
            properties={"path": {"type": "string"}},
            required=["path"],
        ),
    )


async def _artifact_tool(call: Any) -> ToolResult:
    return ToolResult(
        tool_use_id=call.tool_use_id,
        tool_name=call.tool_name,
        content="published",
        artifacts=[
            {
                "id": "art-1",
                "name": "report.txt",
                "mime": "text/plain",
                "size": 12,
                "sha256": "a" * 64,
                "session_id": "session-1",
                "session_key": "agent:main:webchat:session-1",
                "source": "publish_artifact",
                "created_at": "2026-05-06T12:00:00Z",
                "download_url": "/api/v1/artifacts/art-1",
            }
        ],
    )


def test_agent_iteration_defaults_are_unbounded() -> None:
    assert AgentConfig().max_iterations == 0
    assert SubagentSpec(task="check").max_iterations == 0
    assert AgentConfig().max_turn_llm_calls == 0
    assert AgentConfig().max_turn_input_tokens == 0
    assert AgentConfig().max_turn_output_tokens == 0
    assert AgentConfig().max_turn_billed_cost_usd == 0.0
    assert AgentConfig().max_turn_tool_errors == 0
    assert AgentConfig().length_capped_continuations == 1


@pytest.mark.asyncio
async def test_agent_default_max_iterations_allows_long_tool_loop_to_finish() -> None:
    provider = _LoopingToolProvider(final_on_call=101)
    agent = Agent(
        provider=provider,
        config=AgentConfig(),
        tool_definitions=[_echo_definition()],
        tool_handler=_echo_tool,
    )

    events = [event async for event in agent.run_turn("hello")]

    assert len(provider.calls) == 101
    assert not any(event.kind == "error" and event.code == "max_iterations" for event in events)
    assert any(event.kind == "done" and event.text == "done" for event in events)


@pytest.mark.asyncio
async def test_agent_finalizes_when_tool_loop_reaches_max_iterations() -> None:
    provider = _LoopingToolProvider(final_on_call=2)
    agent = Agent(
        provider=provider,
        config=AgentConfig(max_iterations=1),
        tool_definitions=[_echo_definition()],
        tool_handler=_echo_tool,
    )

    events = [event async for event in agent.run_turn("hello")]

    assert len(provider.calls) == 2
    assert provider.calls[-1][-1].role == "user"
    assert "Do not call tools" in str(provider.calls[-1][-1].content)
    assert "Do not call tools" not in "\n".join(
        str(message.content) for message in agent._history
    )
    assert not any(event.kind == "state" and event.state.value == "error" for event in events)
    assert not any(event.kind == "error" and event.code == "max_iterations" for event in events)
    assert any(event.kind == "done" and event.text == "done" for event in events)


@pytest.mark.asyncio
async def test_agent_reports_partial_max_iterations_after_finalization_attempt_fails() -> None:
    provider = _LoopingToolProvider()
    agent = Agent(
        provider=provider,
        config=AgentConfig(max_iterations=1),
        tool_definitions=[_echo_definition()],
        tool_handler=_echo_tool,
    )

    events = [event async for event in agent.run_turn("hello")]

    assert len(provider.calls) == 2
    assert not any(event.kind == "state" and event.state.value == "error" for event in events)
    assert any(
        event.kind == "done"
        and "best partial result" in event.text
        for event in events
    )


@pytest.mark.asyncio
async def test_agent_returns_partial_when_max_iteration_finalization_provider_fails() -> None:
    provider = _ToolThenProviderErrorProvider()
    agent = Agent(
        provider=provider,
        config=AgentConfig(max_iterations=1, max_provider_retries=0),
        tool_definitions=[_echo_definition()],
        tool_handler=_echo_tool,
    )

    events = [event async for event in agent.run_turn("hello")]

    assert len(provider.calls) == 2
    assert not any(event.kind == "state" and event.state.value == "error" for event in events)
    assert not any(event.kind == "error" for event in events)
    done_texts = [event.text for event in events if event.kind == "done"]
    assert len(done_texts) == 1
    assert done_texts[0].count("best partial result") == 1


@pytest.mark.asyncio
async def test_agent_allows_final_response_on_last_iteration() -> None:
    provider = _LoopingToolProvider(final_on_call=2)
    agent = Agent(
        provider=provider,
        config=AgentConfig(max_iterations=2),
        tool_definitions=[_echo_definition()],
        tool_handler=_echo_tool,
    )

    events = [event async for event in agent.run_turn("hello")]

    assert len(provider.calls) == 2
    assert not any(event.kind == "error" and event.code == "max_iterations" for event in events)
    assert any(event.kind == "done" and event.text == "done" for event in events)


@pytest.mark.asyncio
async def test_agent_emits_artifact_event_independent_of_tool_result_text() -> None:
    provider = _LoopingToolProvider()
    agent = Agent(
        provider=provider,
        config=AgentConfig(max_iterations=1),
        tool_definitions=[_echo_definition()],
        tool_handler=_artifact_tool,
    )

    events = [event async for event in agent.run_turn("hello")]

    artifact_events = [event for event in events if isinstance(event, ArtifactEvent)]
    assert len(artifact_events) == 1
    assert artifact_events[0].id == "art-1"
    assert artifact_events[0].download_url == "/api/v1/artifacts/art-1"


@pytest.mark.asyncio
async def test_agent_synthesizes_final_artifact_response_without_provider_call() -> None:
    provider = _ArtifactThenProviderErrorProvider()
    agent = Agent(
        provider=provider,
        config=AgentConfig(max_iterations=3, max_provider_retries=0),
        tool_definitions=[_publish_artifact_definition()],
        tool_handler=_artifact_tool,
    )

    events = [event async for event in agent.run_turn("publish a report")]

    assert len(provider.calls) == 1
    assert any(isinstance(event, ArtifactEvent) for event in events)
    assert not any(isinstance(event, ErrorEvent) for event in events)
    assert not any(event.kind == "warning" for event in events)
    assert any(
        event.kind == "done"
        and event.text == "The generated file is ready: report.txt."
        for event in events
    )


@pytest.mark.asyncio
async def test_agent_synthesizes_final_artifact_response_before_extra_llm_call() -> None:
    provider = _ArtifactThenProviderErrorProvider()
    agent = Agent(
        provider=provider,
        config=AgentConfig(max_iterations=3, max_turn_llm_calls=1),
        tool_definitions=[_publish_artifact_definition()],
        tool_handler=_artifact_tool,
    )

    events = [event async for event in agent.run_turn("publish a report")]

    assert len(provider.calls) == 1
    assert any(isinstance(event, ArtifactEvent) for event in events)
    assert not any(isinstance(event, ErrorEvent) for event in events)
    assert not any(event.kind == "warning" for event in events)
    assert any(
        event.kind == "done"
        and event.text == "The generated file is ready: report.txt."
        for event in events
    )


@pytest.mark.asyncio
async def test_agent_stops_when_turn_input_token_budget_is_exceeded() -> None:
    provider = _LoopingToolProvider()
    agent = Agent(
        provider=provider,
        config=AgentConfig(
            max_iterations=100,
            max_turn_input_tokens=1,
            max_turn_output_tokens=0,
            max_turn_billed_cost_usd=0,
            max_turn_tool_errors=0,
        ),
        tool_definitions=[_echo_definition()],
        tool_handler=_echo_tool,
    )

    events = [event async for event in agent.run_turn("hello")]

    assert len(provider.calls) == 2
    assert any(
        event.kind == "error" and event.code == "turn_input_token_budget_exceeded"
        for event in events
    )


@pytest.mark.asyncio
async def test_agent_stops_when_turn_llm_call_budget_is_exceeded() -> None:
    provider = _LoopingToolProvider()
    agent = Agent(
        provider=provider,
        config=AgentConfig(
            max_iterations=100,
            max_turn_llm_calls=1,
        ),
        tool_definitions=[_echo_definition()],
        tool_handler=_echo_tool,
    )

    events = [event async for event in agent.run_turn("hello")]

    assert len(provider.calls) == 1
    assert any(
        event.kind == "error" and event.code == "turn_llm_call_budget_exceeded"
        for event in events
    )


@pytest.mark.asyncio
async def test_agent_stops_when_turn_output_token_budget_is_exceeded() -> None:
    provider = _DoneUsageProvider(output_tokens=10)
    agent = Agent(
        provider=provider,
        config=AgentConfig(max_turn_output_tokens=5),
    )

    events = [event async for event in agent.run_turn("hello")]

    assert len(provider.calls) == 1
    assert any(
        event.kind == "error" and event.code == "turn_output_token_budget_exceeded"
        for event in events
    )


@pytest.mark.asyncio
async def test_agent_done_event_uses_current_turn_real_billed_usage_delta() -> None:
    tracker = UsageTracker()
    session_key = "agent:test:webchat:s1"
    tracker.add(
        session_key,
        input_tokens=100,
        output_tokens=10,
        model_id="deepseek/deepseek-v4-pro-20260423",
        billed_cost=0.050,
    )
    provider = _DoneUsageProvider(input_tokens=9, output_tokens=4, billed_cost=0.123)
    agent = Agent(
        provider=provider,
        config=AgentConfig(model_id="deepseek/deepseek-v4-pro-20260423"),
        usage_tracker=tracker,
        session_key=session_key,
    )

    events = [event async for event in agent.run_turn("hello")]
    done = next(event for event in events if event.kind == "done")

    assert done.input_tokens == 9
    assert done.output_tokens == 4
    assert done.cost_usd == pytest.approx(0.123)
    assert done.billed_cost == pytest.approx(0.123)
    assert done.cost_source == "provider_billed"
    assert done.session_totals is not None
    assert done.session_totals.billed_cost == pytest.approx(0.173)


@pytest.mark.asyncio
async def test_agent_stops_when_turn_billed_cost_budget_is_exceeded() -> None:
    provider = _DoneUsageProvider(billed_cost=0.25)
    agent = Agent(
        provider=provider,
        config=AgentConfig(max_turn_billed_cost_usd=0.1),
    )

    events = [event async for event in agent.run_turn("hello")]

    assert len(provider.calls) == 1
    assert any(
        event.kind == "error" and event.code == "turn_billed_cost_budget_exceeded"
        for event in events
    )


@pytest.mark.asyncio
async def test_agent_stops_when_turn_tool_error_budget_is_exceeded() -> None:
    provider = _LoopingToolProvider()
    agent = Agent(
        provider=provider,
        config=AgentConfig(
            max_iterations=100,
            max_turn_input_tokens=0,
            max_turn_output_tokens=0,
            max_turn_billed_cost_usd=0,
            max_turn_tool_errors=2,
        ),
        tool_definitions=[_echo_definition()],
        tool_handler=_error_tool,
    )

    events = [event async for event in agent.run_turn("hello")]

    assert len(provider.calls) == 2
    assert any(
        event.kind == "error" and event.code == "turn_tool_error_budget_exceeded"
        for event in events
    )
