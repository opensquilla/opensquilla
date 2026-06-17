from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest

from opensquilla.engine import Agent, AgentConfig, ToolResult
from opensquilla.engine.agent_injection import ListPendingInputProvider
from opensquilla.engine.types import ToolCall
from opensquilla.provider import (
    ChatConfig,
    ContentBlockText,
    Message,
    ToolDefinition,
    ToolInputSchema,
)
from opensquilla.provider import (
    DoneEvent as ProviderDone,
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


class _ToolBoundaryProvider:
    provider_name = "fake"

    def __init__(self, *, tool_iterations: int = 1) -> None:
        self.tool_iterations = tool_iterations
        self.calls: list[list[Message]] = []

    def chat(
        self,
        messages: list[Message],
        tools: list[Any] | None = None,
        config: ChatConfig | None = None,
    ) -> AsyncIterator[Any]:
        self.calls.append(list(messages))
        return self._stream(len(self.calls))

    async def _stream(self, call_number: int) -> AsyncIterator[Any]:
        if call_number <= self.tool_iterations:
            tool_use_id = f"tool-{call_number}"
            yield ProviderToolUseStart(tool_use_id=tool_use_id, tool_name="echo")
            yield ProviderToolUseEnd(
                tool_use_id=tool_use_id,
                tool_name="echo",
                arguments={"value": call_number},
            )
            yield ProviderDone(stop_reason="tool_use", input_tokens=1, output_tokens=1)
            return

        yield ProviderText(text="done")
        yield ProviderDone(stop_reason="stop", input_tokens=1, output_tokens=1)

    async def list_models(self) -> list[Any]:
        return []


class _NoToolProvider:
    provider_name = "fake"

    def __init__(self) -> None:
        self.calls: list[list[Message]] = []

    def chat(
        self,
        messages: list[Message],
        tools: list[Any] | None = None,
        config: ChatConfig | None = None,
    ) -> AsyncIterator[Any]:
        self.calls.append(list(messages))
        return self._stream()

    async def _stream(self) -> AsyncIterator[Any]:
        yield ProviderText(text="done")
        yield ProviderDone(stop_reason="stop", input_tokens=1, output_tokens=1)

    async def list_models(self) -> list[Any]:
        return []


def _tool_def(name: str) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=f"Mock {name}.",
        input_schema=ToolInputSchema(properties={}, required=[]),
    )


async def _tool_handler(call: ToolCall) -> ToolResult:
    return ToolResult(
        tool_use_id=call.tool_use_id,
        tool_name=call.tool_name,
        content=f"result from {call.tool_name} {call.tool_use_id}",
    )


def _agent(provider: Any, *, max_iterations: int = 3) -> Agent:
    return Agent(
        provider=provider,
        config=AgentConfig(max_iterations=max_iterations),
        tool_definitions=[_tool_def("echo")],
        tool_handler=_tool_handler,
    )


def _text_block_texts(message: Message) -> list[str]:
    if not isinstance(message.content, list):
        return []
    return [block.text for block in message.content if isinstance(block, ContentBlockText)]


def _is_tool_result_message(message: Message) -> bool:
    return message.role == "user" and isinstance(message.content, list) and any(
        getattr(block, "type", None) == "tool_result" for block in message.content
    )


def _tool_result_index(messages: list[Message]) -> int:
    return next(index for index, message in enumerate(messages) if _is_tool_result_message(message))


def _text_message_index(messages: list[Message], texts: list[str]) -> int:
    return next(
        index
        for index, message in enumerate(messages)
        if message.role == "user" and _text_block_texts(message) == texts
    )


def _text_messages(messages: list[Message], texts: list[str]) -> list[Message]:
    return [
        message
        for message in messages
        if message.role == "user" and _text_block_texts(message) == texts
    ]


@pytest.mark.asyncio
async def test_pending_input_is_injected_after_tool_result_and_seen_by_next_model_request() -> None:
    provider = _ToolBoundaryProvider()
    pending = ListPendingInputProvider()
    pending.append("INJECTED")
    agent = _agent(provider)

    events = [event async for event in agent.run_turn("run echo", pending_input_provider=pending)]

    assert len(provider.calls) == 2
    second_request = provider.calls[1]
    assert _text_message_index(second_request, ["INJECTED"]) == (
        _tool_result_index(second_request) + 1
    )
    assert any(event.kind == "done" and event.text == "done" for event in events)


@pytest.mark.asyncio
async def test_multiple_pending_inputs_are_merged_into_one_user_message() -> None:
    provider = _ToolBoundaryProvider()
    pending = ListPendingInputProvider()
    pending.append("A")
    pending.append("B")
    agent = _agent(provider)

    _events = [event async for event in agent.run_turn("run echo", pending_input_provider=pending)]

    second_request = provider.calls[1]
    injected_messages = _text_messages(second_request, ["A", "B"])
    assert len(injected_messages) == 1
    assert isinstance(injected_messages[0].content, list)
    assert _text_block_texts(injected_messages[0]) == ["A", "B"]
    assert not _text_messages(second_request, ["A"])
    assert not _text_messages(second_request, ["B"])


@pytest.mark.asyncio
async def test_no_pending_provider_keeps_tool_result_last_in_next_request() -> None:
    provider = _ToolBoundaryProvider()
    agent = _agent(provider)

    _events = [event async for event in agent.run_turn("run echo")]

    assert len(provider.calls) == 2
    assert _is_tool_result_message(provider.calls[1][-1])


@pytest.mark.asyncio
async def test_drained_pending_input_is_not_injected_again_at_later_tool_boundaries() -> None:
    provider = _ToolBoundaryProvider(tool_iterations=2)
    pending = ListPendingInputProvider()
    pending.append("ONCE")
    agent = _agent(provider, max_iterations=3)

    _events = [event async for event in agent.run_turn("run echo", pending_input_provider=pending)]

    assert len(provider.calls) == 3
    assert len(pending) == 0
    assert len(_text_messages(agent._history, ["ONCE"])) == 1


@pytest.mark.asyncio
async def test_injected_pending_input_is_persisted_to_successful_turn_history() -> None:
    provider = _ToolBoundaryProvider()
    pending = ListPendingInputProvider()
    pending.append("HISTORY")
    agent = _agent(provider)

    _events = [event async for event in agent.run_turn("run echo", pending_input_provider=pending)]

    assert _text_message_index(agent._history, ["HISTORY"]) == (
        _tool_result_index(agent._history) + 1
    )


@pytest.mark.asyncio
async def test_pending_input_is_not_drained_without_a_tool_completion_boundary() -> None:
    provider = _NoToolProvider()
    pending = ListPendingInputProvider()
    pending.append("NO_BOUNDARY")
    agent = _agent(provider)

    _events = [
        event async for event in agent.run_turn("just answer", pending_input_provider=pending)
    ]

    assert len(provider.calls) == 1
    assert len(pending) == 1
    assert not _text_messages(agent._history, ["NO_BOUNDARY"])
