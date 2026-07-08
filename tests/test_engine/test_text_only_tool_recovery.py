from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import pytest

from opensquilla.engine import Agent, AgentConfig, ToolResult
from opensquilla.provider import DoneEvent as ProviderDone
from opensquilla.provider import TextDeltaEvent as ProviderText
from opensquilla.provider import ToolDefinition, ToolInputSchema
from opensquilla.provider import ToolUseEndEvent as ProviderToolUseEnd
from opensquilla.provider import ToolUseStartEvent as ProviderToolUseStart


class _SequenceProvider:
    provider_name = "fake"

    def __init__(self, streams: list[list[Any]]) -> None:
        self.streams = streams
        self.calls: list[dict[str, Any]] = []

    def chat(self, messages, tools=None, config=None) -> AsyncIterator[Any]:  # noqa: ANN001
        index = len(self.calls)
        self.calls.append({"messages": messages, "tools": tools, "config": config})
        events = self.streams[index] if index < len(self.streams) else self.streams[-1]
        return self._stream(events)

    async def _stream(self, events: list[Any]) -> AsyncIterator[Any]:
        for event in events:
            yield event

    async def list_models(self) -> list[Any]:
        return []


@pytest.mark.asyncio
async def test_text_only_recovery_warns_then_records_next_tool_action(tmp_path) -> None:
    provider = _SequenceProvider(
        [
            [
                ProviderText(text="I should inspect the repository."),
                ProviderDone(stop_reason="stop", input_tokens=3, output_tokens=1),
            ],
            [
                ProviderToolUseStart(tool_use_id="tool-1", tool_name="echo"),
                ProviderToolUseEnd(
                    tool_use_id="tool-1",
                    tool_name="echo",
                    arguments={"value": "ok"},
                ),
                ProviderDone(stop_reason="tool_use", input_tokens=4, output_tokens=1),
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

    runtime_events_path = tmp_path / "runtime_events.jsonl"
    agent = Agent(
        provider=provider,
        config=AgentConfig(
            max_iterations=3,
            text_only_tool_recovery_mode="warn_model",
            runtime_events_path=str(runtime_events_path),
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
        event.kind == "warning" and event.code == "text_only_tool_recovery"
        for event in events
    )
    assert len(provider.calls) == 3
    assert any(
        msg.role == "user"
        and isinstance(msg.content, str)
        and "Previous assistant turn had text only" in msg.content
        for msg in provider.calls[1]["messages"]
    )
    assert not any(
        msg.role == "user"
        and isinstance(msg.content, str)
        and "Previous assistant turn had text only" in msg.content
        for msg in agent._history
    )
    logged = [json.loads(line) for line in runtime_events_path.read_text().splitlines()]
    recovery = [
        event for event in logged if event.get("mechanism") == "text_only_tool_recovery"
    ]
    assert [event["action"] for event in recovery] == ["nudge", "observe"]
    assert recovery[0]["injected_to_model"] is True
    assert recovery[1]["details"]["next_action"] == "tool_call"


@pytest.mark.asyncio
async def test_text_only_recovery_log_mode_does_not_inject(tmp_path) -> None:
    provider = _SequenceProvider(
        [
            [
                ProviderText(text="I should inspect the repository."),
                ProviderDone(stop_reason="stop", input_tokens=3, output_tokens=1),
            ]
        ]
    )
    agent = Agent(
        provider=provider,
        config=AgentConfig(
            max_iterations=1,
            text_only_tool_recovery_mode="log",
            runtime_events_path=str(tmp_path / "runtime_events.jsonl"),
        ),
        tool_definitions=[
            ToolDefinition(
                name="echo",
                description="Echo.",
                input_schema=ToolInputSchema(properties={}, required=[]),
            )
        ],
    )

    events = [event async for event in agent.run_turn("hello")]

    assert any(event.kind == "done" for event in events)
    assert len(provider.calls) == 1
