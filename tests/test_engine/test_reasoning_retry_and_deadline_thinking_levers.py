"""Opt-in levers: reasoning-only thinking fallback + pre-deadline thinking cutoff.

Covers OPENSQUILLA_REASONING_ONLY_THINKING_FALLBACK and
OPENSQUILLA_DEADLINE_THINKING_OFF_MARGIN_SECONDS (both off by default).
Motivation: with some providers a reasoning-only response is best retried with
thinking disabled (the retry otherwise re-enters a long reasoning stream), and
deadline-capped runs can spend their whole final margin inside one reasoning
stream instead of applying and verifying changes.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest

from opensquilla.engine import Agent, AgentConfig, ThinkingLevel, ToolResult
from opensquilla.provider import (
    ChatConfig,
    Message,
    ToolDefinition,
    ToolInputSchema,
)
from opensquilla.provider import DoneEvent as ProviderDone
from opensquilla.provider import TextDeltaEvent as ProviderText
from opensquilla.provider import ToolUseEndEvent as ProviderToolUseEnd
from opensquilla.provider import ToolUseStartEvent as ProviderToolUseStart


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


def _reasoning_only_done() -> list[Any]:
    return [
        ProviderDone(
            stop_reason="stop",
            input_tokens=10,
            output_tokens=5,
            reasoning_tokens=5,
            reasoning_content="internal reasoning",
        )
    ]


def _final_text() -> list[Any]:
    return [
        ProviderText(text="ok"),
        ProviderDone(stop_reason="stop", input_tokens=11, output_tokens=1),
    ]


def _echo_tool_call(tool_use_id: str) -> list[Any]:
    return [
        ProviderToolUseStart(tool_use_id=tool_use_id, tool_name="echo"),
        ProviderToolUseEnd(
            tool_use_id=tool_use_id,
            tool_name="echo",
            arguments={"value": "hi"},
        ),
        ProviderDone(stop_reason="tool_use", input_tokens=3, output_tokens=1),
    ]


def _echo_agent(provider: _SequenceProvider, config: AgentConfig) -> Agent:
    async def tool_handler(call: object) -> ToolResult:
        return ToolResult(
            tool_use_id=getattr(call, "tool_use_id"),
            tool_name=getattr(call, "tool_name"),
            content="tool ok",
        )

    return Agent(
        provider=provider,
        config=config,
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


@pytest.mark.asyncio
async def test_reasoning_only_fallback_disables_thinking_on_retry() -> None:
    provider = _SequenceProvider([_reasoning_only_done(), _final_text()])
    agent = Agent(
        provider=provider,
        config=AgentConfig(
            thinking=ThinkingLevel.MEDIUM,
            reasoning_only_thinking_fallback=True,
            retry_base_backoff_ms=0,
            retry_max_backoff_ms=0,
        ),
    )

    events = [event async for event in agent.run_turn("hello")]

    assert [event.kind for event in events if event.kind == "error"] == []
    warning = next(
        event
        for event in events
        if event.kind == "warning" and event.code == "provider_reasoning_only_retry"
    )
    assert "thinking disabled" in warning.message
    done = next(event for event in events if event.kind == "done")
    assert done.text == "ok"
    assert len(provider.calls) == 2
    assert provider.calls[0]["config"].thinking is True
    assert provider.calls[1]["config"].thinking is False


@pytest.mark.asyncio
async def test_reasoning_only_fallback_default_off_keeps_thinking() -> None:
    provider = _SequenceProvider([_reasoning_only_done(), _final_text()])
    agent = Agent(
        provider=provider,
        config=AgentConfig(
            thinking=ThinkingLevel.MEDIUM,
            retry_base_backoff_ms=0,
            retry_max_backoff_ms=0,
        ),
    )

    events = [event async for event in agent.run_turn("hello")]

    warning = next(
        event
        for event in events
        if event.kind == "warning" and event.code == "provider_reasoning_only_retry"
    )
    assert "thinking disabled" not in warning.message
    assert len(provider.calls) == 2
    assert provider.calls[1]["config"].thinking is True


@pytest.mark.asyncio
async def test_reasoning_only_fallback_restores_thinking_after_retry_call() -> None:
    # Retry (thinking off) returns a tool call; the next iteration's provider
    # call must run with thinking re-enabled — the fallback is one-shot.
    provider = _SequenceProvider(
        [_reasoning_only_done(), _echo_tool_call("use-1"), _final_text()]
    )
    agent = _echo_agent(
        provider,
        AgentConfig(
            thinking=ThinkingLevel.MEDIUM,
            reasoning_only_thinking_fallback=True,
            max_iterations=5,
            retry_base_backoff_ms=0,
            retry_max_backoff_ms=0,
        ),
    )

    events = [event async for event in agent.run_turn("hello")]

    assert any(event.kind == "done" for event in events)
    assert len(provider.calls) == 3
    assert provider.calls[0]["config"].thinking is True
    assert provider.calls[1]["config"].thinking is False
    assert provider.calls[2]["config"].thinking is True


@pytest.mark.asyncio
async def test_deadline_thinking_off_disables_thinking_when_margin_reached() -> None:
    provider = _SequenceProvider([_final_text()])
    # margin > timeout: the cutoff arms at the first loop-top check.
    agent = Agent(
        provider=provider,
        config=AgentConfig(
            thinking=ThinkingLevel.MEDIUM,
            timeout=30.0,
            deadline_thinking_off_margin_seconds=60,
        ),
    )

    events = [event async for event in agent.run_turn("fix the bug")]

    assert any(event.kind == "done" for event in events)
    assert provider.calls[0]["config"].thinking is False


@pytest.mark.asyncio
async def test_deadline_thinking_off_stays_off_for_subsequent_calls() -> None:
    provider = _SequenceProvider([_echo_tool_call("use-1"), _final_text()])
    agent = _echo_agent(
        provider,
        AgentConfig(
            thinking=ThinkingLevel.MEDIUM,
            timeout=30.0,
            deadline_thinking_off_margin_seconds=60,
            max_iterations=5,
            retry_base_backoff_ms=0,
            retry_max_backoff_ms=0,
        ),
    )

    events = [event async for event in agent.run_turn("fix the bug")]

    assert any(event.kind == "done" for event in events)
    assert len(provider.calls) == 2
    # Sticky: every call after arming runs with thinking off.
    assert provider.calls[0]["config"].thinking is False
    assert provider.calls[1]["config"].thinking is False


@pytest.mark.asyncio
async def test_deadline_thinking_off_default_off() -> None:
    provider = _SequenceProvider([_final_text()])
    agent = Agent(
        provider=provider,
        config=AgentConfig(thinking=ThinkingLevel.MEDIUM, timeout=30.0),
    )

    events = [event async for event in agent.run_turn("fix the bug")]

    assert any(event.kind == "done" for event in events)
    assert provider.calls[0]["config"].thinking is True


@pytest.mark.asyncio
async def test_deadline_thinking_off_not_armed_when_margin_not_reached() -> None:
    provider = _SequenceProvider([_final_text()])
    # Large timeout, small margin: the trigger stays far in the future.
    agent = Agent(
        provider=provider,
        config=AgentConfig(
            thinking=ThinkingLevel.MEDIUM,
            timeout=3600.0,
            deadline_thinking_off_margin_seconds=60,
        ),
    )

    events = [event async for event in agent.run_turn("fix the bug")]

    assert any(event.kind == "done" for event in events)
    assert provider.calls[0]["config"].thinking is True


def test_env_plumbing_for_both_levers(monkeypatch: pytest.MonkeyPatch) -> None:
    # Helper-level check only; the full env -> bootstrap-stage -> AgentConfig
    # threading is covered in turn_runner/test_agent_bootstrap_stage_unit.py.
    from opensquilla.engine.turn_runner.agent_bootstrap_stage import (
        _bool_from_env,
        _nonnegative_int_from_env,
    )

    monkeypatch.delenv("OPENSQUILLA_REASONING_ONLY_THINKING_FALLBACK", raising=False)
    monkeypatch.delenv("OPENSQUILLA_DEADLINE_THINKING_OFF_MARGIN_SECONDS", raising=False)
    assert _bool_from_env("OPENSQUILLA_REASONING_ONLY_THINKING_FALLBACK", False) is False
    assert (
        _nonnegative_int_from_env("OPENSQUILLA_DEADLINE_THINKING_OFF_MARGIN_SECONDS", 0)
        == 0
    )
    monkeypatch.setenv("OPENSQUILLA_REASONING_ONLY_THINKING_FALLBACK", "1")
    monkeypatch.setenv("OPENSQUILLA_DEADLINE_THINKING_OFF_MARGIN_SECONDS", "480")
    assert _bool_from_env("OPENSQUILLA_REASONING_ONLY_THINKING_FALLBACK", False) is True
    assert (
        _nonnegative_int_from_env("OPENSQUILLA_DEADLINE_THINKING_OFF_MARGIN_SECONDS", 0)
        == 480
    )


def test_agent_config_defaults_keep_both_levers_off() -> None:
    config = AgentConfig()

    assert config.reasoning_only_thinking_fallback is False
    assert config.deadline_thinking_off_margin_seconds == 0
