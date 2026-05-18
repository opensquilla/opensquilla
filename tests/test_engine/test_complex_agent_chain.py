from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from opensquilla.engine import Agent, AgentConfig, ToolResult
from opensquilla.engine.types import ToolCall
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
    TextDeltaEvent as ProviderText,
)
from opensquilla.provider import (
    ToolUseEndEvent as ProviderToolUseEnd,
)
from opensquilla.provider import (
    ToolUseStartEvent as ProviderToolUseStart,
)


class _ComplexTaskProvider:
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
        return self._stream(len(self.calls))

    async def _stream(self, call_number: int) -> AsyncIterator[Any]:
        if call_number == 1:
            yield ProviderToolUseStart(tool_use_id="search-1", tool_name="web_search")
            yield ProviderToolUseEnd(
                tool_use_id="search-1",
                tool_name="web_search",
                arguments={"query": "opensquilla regression"},
            )
            yield ProviderToolUseStart(tool_use_id="read-1", tool_name="read_file")
            yield ProviderToolUseEnd(
                tool_use_id="read-1",
                tool_name="read_file",
                arguments={"path": "README.md"},
            )
            yield ProviderDone(stop_reason="tool_use", input_tokens=10, output_tokens=2)
            return

        if call_number == 2:
            yield ProviderToolUseStart(tool_use_id="cmd-1", tool_name="exec_command")
            yield ProviderToolUseEnd(
                tool_use_id="cmd-1",
                tool_name="exec_command",
                arguments={"cmd": "pytest targeted"},
            )
            yield ProviderDone(stop_reason="tool_use", input_tokens=12, output_tokens=2)
            return

        yield ProviderText(text="complex chain complete")
        yield ProviderDone(stop_reason="stop", input_tokens=14, output_tokens=3)

    async def list_models(self) -> list[Any]:
        return []


def _tool_def(name: str, properties: dict[str, Any]) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=f"Mock {name}.",
        input_schema=ToolInputSchema(
            properties=properties,
            required=list(properties),
        ),
    )


def test_complex_agent_chain_runs_multi_tool_multi_iteration_task() -> None:
    async def run() -> None:
        provider = _ComplexTaskProvider()
        handled: list[tuple[str, dict[str, Any]]] = []

        async def tool_handler(call: ToolCall) -> ToolResult:
            handled.append((call.tool_name, dict(call.arguments)))
            return ToolResult(
                tool_use_id=call.tool_use_id,
                tool_name=call.tool_name,
                content=json.dumps(
                    {
                        "ok": True,
                        "tool": call.tool_name,
                        "arguments": call.arguments,
                    },
                    sort_keys=True,
                ),
            )

        agent = Agent(
            provider=provider,
            config=AgentConfig(max_iterations=3),
            tool_definitions=[
                _tool_def("web_search", {"query": {"type": "string"}}),
                _tool_def("read_file", {"path": {"type": "string"}}),
                _tool_def("exec_command", {"cmd": {"type": "string"}}),
            ],
            tool_handler=tool_handler,
        )

        events = [event async for event in agent.run_turn("diagnose the regression")]

        assert [name for name, _args in handled] == [
            "web_search",
            "read_file",
            "exec_command",
        ]
        assert len(provider.calls) == 3
        assert any(
            event.kind == "done" and event.text == "complex chain complete"
            for event in events
        )

        second_call = provider.calls[1]
        assert any(
            message.role == "assistant"
            and any(getattr(block, "id", "") == "search-1" for block in message.content)
            for message in second_call
        )
        assert any(
            message.role == "user"
            and any(getattr(block, "tool_use_id", "") == "search-1" for block in message.content)
            for message in second_call
        )
        third_call = provider.calls[2]
        assert any(
            message.role == "user"
            and any(getattr(block, "tool_use_id", "") == "cmd-1" for block in message.content)
            for message in third_call
        )

    asyncio.run(run())
