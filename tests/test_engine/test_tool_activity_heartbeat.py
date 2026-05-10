from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest

from opensquilla.engine import Agent, AgentConfig, ToolResult
from opensquilla.engine.types import RunHeartbeatEvent, ToolCall, ToolResultEvent
from opensquilla.provider import ChatConfig, Message, ToolDefinition, ToolInputSchema
from opensquilla.provider import DoneEvent as ProviderDone
from opensquilla.provider import ToolUseEndEvent as ProviderToolUseEnd
from opensquilla.provider import ToolUseStartEvent as ProviderToolUseStart


class _OneToolProvider:
    provider_name = "fake"

    def __init__(self, tool_name: str = "slow_tool") -> None:
        self.tool_name = tool_name
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
        yield ProviderToolUseStart(tool_use_id="tool-1", tool_name=self.tool_name)
        yield ProviderToolUseEnd(
            tool_use_id="tool-1",
            tool_name=self.tool_name,
            arguments={},
        )
        yield ProviderDone(stop_reason="tool_use", input_tokens=1, output_tokens=1)

    async def list_models(self) -> list[Any]:
        return []


def _tool_def(name: str = "slow_tool") -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=f"Mock tool {name}",
        input_schema=ToolInputSchema(properties={}, required=[]),
    )


@pytest.mark.asyncio
async def test_long_active_tool_emits_run_heartbeat_before_tool_result() -> None:
    async def _handler(tc: ToolCall) -> ToolResult:
        await asyncio.sleep(0.08)
        return ToolResult(
            tool_use_id=tc.tool_use_id,
            tool_name=tc.tool_name,
            content="ok",
        )

    agent = Agent(
        provider=_OneToolProvider(),
        config=AgentConfig(
            max_iterations=1,
            tool_timeout=1.0,
            metadata={"tool_activity_heartbeat_interval": 0.02},
        ),
        tool_definitions=[_tool_def()],
        tool_handler=_handler,
    )

    events = [event async for event in agent.run_turn("run")]
    heartbeat_index = next(
        index for index, event in enumerate(events) if isinstance(event, RunHeartbeatEvent)
    )
    result_index = next(
        index for index, event in enumerate(events) if isinstance(event, ToolResultEvent)
    )

    heartbeat = events[heartbeat_index]
    assert isinstance(heartbeat, RunHeartbeatEvent)
    assert heartbeat.phase == "tool"
    assert heartbeat_index < result_index
    result = events[result_index]
    assert isinstance(result, ToolResultEvent)
    assert result.result == "ok"


@pytest.mark.asyncio
async def test_tool_activity_heartbeat_does_not_extend_tool_timeout() -> None:
    cancelled = asyncio.Event()

    async def _handler(tc: ToolCall) -> ToolResult:
        try:
            await asyncio.sleep(2.0)
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return ToolResult(
            tool_use_id=tc.tool_use_id,
            tool_name=tc.tool_name,
            content="late",
        )

    agent = Agent(
        provider=_OneToolProvider(),
        config=AgentConfig(
            max_iterations=1,
            tool_timeout=0.06,
            metadata={"tool_activity_heartbeat_interval": 0.02},
        ),
        tool_definitions=[_tool_def()],
        tool_handler=_handler,
    )

    events = [event async for event in agent.run_turn("run")]
    result = next(event for event in events if isinstance(event, ToolResultEvent))

    assert any(isinstance(event, RunHeartbeatEvent) for event in events)
    assert cancelled.is_set()
    assert result.is_error
    assert result.result.startswith("Tool 'slow_tool' timed out after ")


@pytest.mark.asyncio
async def test_tool_task_cancellation_becomes_tool_error_without_cancelling_turn() -> None:
    async def _handler(tc: ToolCall) -> ToolResult:
        raise asyncio.CancelledError

    agent = Agent(
        provider=_OneToolProvider(),
        config=AgentConfig(max_iterations=1),
        tool_definitions=[_tool_def()],
        tool_handler=_handler,
    )

    events = [event async for event in agent.run_turn("run")]
    result = next(event for event in events if isinstance(event, ToolResultEvent))

    assert result.is_error
    assert result.result == "Tool 'slow_tool' was cancelled"
