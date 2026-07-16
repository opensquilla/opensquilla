from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

import opensquilla.engine.agent as agent_mod
from opensquilla.engine import Agent, AgentConfig, ToolCall, ToolResult
from opensquilla.engine.types import ToolResultEvent
from opensquilla.provider import TextDeltaEvent, ToolDefinition, ToolInputSchema
from opensquilla.provider import DoneEvent as ProviderDoneEvent
from opensquilla.provider import ToolUseEndEvent as ProviderToolUseEndEvent
from opensquilla.provider import ToolUseStartEvent as ProviderToolUseStartEvent


class _SingleToolProvider:
    provider_name = "fake"

    def __init__(self, *, tool_name: str, arguments: dict[str, Any]) -> None:
        self.tool_name = tool_name
        self.arguments = arguments
        self.calls: list[list[Any]] = []

    def chat(self, messages, tools=None, config=None):
        self.calls.append(messages)
        return self._stream(len(self.calls))

    async def _stream(self, call_number: int):
        if call_number == 1:
            yield ProviderToolUseStartEvent(
                tool_use_id="tool-1",
                tool_name=self.tool_name,
            )
            yield ProviderToolUseEndEvent(
                tool_use_id="tool-1",
                tool_name=self.tool_name,
                arguments=self.arguments,
            )
            yield ProviderDoneEvent(stop_reason="tool_use", input_tokens=1, output_tokens=1)
            return
        yield TextDeltaEvent(text="done")
        yield ProviderDoneEvent(stop_reason="stop", input_tokens=1, output_tokens=1)

    async def list_models(self) -> list[Any]:
        return []


def _tool_def(name: str) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=f"Mock tool {name}",
        input_schema=ToolInputSchema(properties={}, required=[]),
    )


def _tool_result_events(events: list[Any]) -> list[ToolResultEvent]:
    return [event for event in events if isinstance(event, ToolResultEvent)]


@pytest.mark.asyncio
async def test_ordinary_tool_result_event_delivers_sources_separately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        agent_mod,
        "reduce_tool_result_with_tokenjuice",
        lambda **_kwargs: None,
        raising=False,
    )
    sources = [
        {
            "source_id": "source-1",
            "title": "Primary source",
            "url": "https://example.com/source-1",
        }
    ]

    async def handler(tool_call: ToolCall) -> ToolResult:
        return ToolResult(
            tool_use_id=tool_call.tool_use_id,
            tool_name=tool_call.tool_name,
            content="MODEL_VISIBLE_RESULT",
            sources=sources,
        )

    provider = _SingleToolProvider(tool_name="knowledge_search", arguments={})
    agent = Agent(
        provider=provider,
        config=AgentConfig(context_window_tokens=1_000_000, max_iterations=2),
        tool_definitions=[_tool_def("knowledge_search")],
        tool_handler=handler,
    )

    events = [event async for event in agent.run_turn("search")]

    [result_event] = _tool_result_events(events)
    assert result_event.result == "MODEL_VISIBLE_RESULT"
    assert result_event.sources == sources
    assert "source-1" not in result_event.result
    assert "example.com" not in result_event.result


@pytest.mark.asyncio
async def test_ordinary_tool_result_event_defaults_sources_to_empty_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        agent_mod,
        "reduce_tool_result_with_tokenjuice",
        lambda **_kwargs: None,
        raising=False,
    )

    async def handler(tool_call: ToolCall) -> ToolResult:
        return ToolResult(
            tool_use_id=tool_call.tool_use_id,
            tool_name=tool_call.tool_name,
            content="NO_SOURCES",
        )

    provider = _SingleToolProvider(tool_name="local_tool", arguments={})
    agent = Agent(
        provider=provider,
        config=AgentConfig(context_window_tokens=1_000_000, max_iterations=2),
        tool_definitions=[_tool_def("local_tool")],
        tool_handler=handler,
    )

    events = [event async for event in agent.run_turn("run")]

    [result_event] = _tool_result_events(events)
    assert result_event.result == "NO_SOURCES"
    assert result_event.sources == []


@pytest.mark.asyncio
async def test_projected_tool_result_event_uses_original_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projected_content = "[tokenjuice]\nimportant failure"

    def fake_reduce(**kwargs: Any) -> Any:
        return SimpleNamespace(
            inline_text=projected_content,
            raw_chars=len(kwargs["content"]),
            reduced_chars=len(projected_content),
            ratio=0.01,
            reducer="tests/pytest",
        )

    monkeypatch.setattr(
        agent_mod,
        "reduce_tool_result_with_tokenjuice",
        fake_reduce,
        raising=False,
    )
    sources = [
        {
            "source_id": "diagnostic-1",
            "title": "Diagnostic source",
            "url": "https://example.com/diagnostic-1",
        }
    ]
    raw_output = "pytest output\n" + ("traceback frame\n" * 500)

    async def handler(tool_call: ToolCall) -> ToolResult:
        return ToolResult(
            tool_use_id=tool_call.tool_use_id,
            tool_name=tool_call.tool_name,
            content=raw_output,
            is_error=True,
            sources=sources,
        )

    provider = _SingleToolProvider(
        tool_name="exec_command",
        arguments={"command": "pytest -q", "workdir": "/repo"},
    )
    agent = Agent(
        provider=provider,
        config=AgentConfig(
            context_window_tokens=1_000_000,
            max_iterations=2,
            tool_result_fresh_diagnostic_policy_enabled=False,
        ),
        tool_definitions=[_tool_def("exec_command")],
        tool_handler=handler,
    )

    events = [event async for event in agent.run_turn("run tests")]

    [result_event] = _tool_result_events(events)
    assert result_event.result == projected_content
    assert result_event.result != raw_output
    assert result_event.sources == sources
    assert "diagnostic-1" not in result_event.result


@pytest.mark.asyncio
async def test_approval_retry_result_event_uses_each_finalized_result_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        agent_mod,
        "reduce_tool_result_with_tokenjuice",
        lambda **_kwargs: None,
        raising=False,
    )
    approval_sources = [
        {
            "source_id": "approval-policy",
            "title": "Approval policy",
            "url": "https://example.com/approval-policy",
        }
    ]
    resumed_sources = [
        {
            "source_id": "execution-receipt",
            "title": "Execution receipt",
            "url": "https://example.com/execution-receipt",
        }
    ]
    approval_payload = json.dumps(
        {
            "status": "approval_required",
            "approval_id": "approval-1",
            "message": "Approve this command.",
        }
    )
    calls = 0

    async def handler(tool_call: ToolCall) -> ToolResult:
        nonlocal calls
        calls += 1
        if calls == 1:
            return ToolResult(
                tool_use_id=tool_call.tool_use_id,
                tool_name=tool_call.tool_name,
                content=approval_payload,
                sources=approval_sources,
            )
        assert tool_call.arguments["approval_id"] == "approval-1"
        return ToolResult(
            tool_use_id=tool_call.tool_use_id,
            tool_name=tool_call.tool_name,
            content="FINAL_OK",
            sources=resumed_sources,
        )

    provider = _SingleToolProvider(
        tool_name="exec_command",
        arguments={"command": "deploy"},
    )
    agent = Agent(
        provider=provider,
        config=AgentConfig(context_window_tokens=1_000_000, max_iterations=2),
        tool_definitions=[_tool_def("exec_command")],
        tool_handler=handler,
    )

    events = [event async for event in agent.run_turn("deploy")]

    approval_event, resumed_event = _tool_result_events(events)
    assert json.loads(approval_event.result)["status"] == "approval_required"
    assert approval_event.sources == approval_sources
    assert resumed_event.result == "FINAL_OK"
    assert resumed_event.sources == resumed_sources
    assert "execution-receipt" not in resumed_event.result
