"""Opt-in mid-budget no-source-diff nudge lever.

Covers OPENSQUILLA_MID_BUDGET_NO_DIFF_NUDGE (off by default). Motivation: a
run that spends most of its wall-clock budget investigating without ever
editing a file usually ends with no diff at all; a one-shot progress nudge
when 50% and again when 75% of the budget is spent with no workspace change
prompts the model to start implementing while there is still time. The nudge
stays quiet whenever any change evidence exists (write receipts, captured
diff candidates, or a live workspace diff).
"""

from __future__ import annotations

import asyncio
import subprocess
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from opensquilla.engine import Agent, AgentConfig, ToolResult
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
from opensquilla.tools.types import CallerKind, ToolContext

_NUDGE_MARKER = "Progress check: about"


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
            # Float entries model wall-clock time passing inside the provider
            # stream, so budget-fraction tests can cross their checkpoints.
            if isinstance(event, float):
                await asyncio.sleep(event)
                continue
            yield event

    async def list_models(self) -> list[Any]:
        return []


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


def _echo_agent(
    provider: _SequenceProvider,
    config: AgentConfig,
    tool_context: ToolContext | None = None,
) -> Agent:
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
        tool_context=tool_context,
    )


def _message_text(message: Any) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content or []:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            parts.append(text)
    return "\n".join(parts)


def _nudge_texts(call: dict[str, Any]) -> list[str]:
    return [
        _message_text(message)
        for message in call["messages"]
        if getattr(message, "role", "") == "user"
        and _NUDGE_MARKER in _message_text(message)
    ]


def _lever_config(**overrides: Any) -> AgentConfig:
    settings: dict[str, Any] = {
        "mid_budget_no_diff_nudge": True,
        "timeout": 2.0,
        "max_iterations": 6,
        "retry_base_backoff_ms": 0,
        "retry_max_backoff_ms": 0,
    }
    settings.update(overrides)
    return AgentConfig(**settings)


@pytest.mark.asyncio
async def test_nudge_fires_once_past_half_budget_without_diff() -> None:
    provider = _SequenceProvider([[1.2, *_echo_tool_call("use-1")], _final_text()])
    agent = _echo_agent(provider, _lever_config())

    events = [event async for event in agent.run_turn("fix the bug")]

    assert any(event.kind == "done" for event in events)
    assert len(provider.calls) == 2
    assert _nudge_texts(provider.calls[0]) == []
    nudges = _nudge_texts(provider.calls[1])
    assert len(nudges) == 1
    assert "50%" in nudges[0]


@pytest.mark.asyncio
async def test_nudge_default_off() -> None:
    provider = _SequenceProvider([[1.2, *_echo_tool_call("use-1")], _final_text()])
    agent = _echo_agent(
        provider,
        AgentConfig(
            timeout=2.0,
            max_iterations=6,
            retry_base_backoff_ms=0,
            retry_max_backoff_ms=0,
        ),
    )

    events = [event async for event in agent.run_turn("fix the bug")]

    assert any(event.kind == "done" for event in events)
    assert all(_nudge_texts(call) == [] for call in provider.calls)


@pytest.mark.asyncio
async def test_nudge_not_fired_before_half_budget() -> None:
    provider = _SequenceProvider([[0.3, *_echo_tool_call("use-1")], _final_text()])
    agent = _echo_agent(provider, _lever_config())

    events = [event async for event in agent.run_turn("fix the bug")]

    assert any(event.kind == "done" for event in events)
    assert all(_nudge_texts(call) == [] for call in provider.calls)


@pytest.mark.asyncio
async def test_nudge_fires_at_both_checkpoints_in_sequence() -> None:
    provider = _SequenceProvider(
        [
            [1.1, *_echo_tool_call("use-1")],
            [0.5, *_echo_tool_call("use-2")],
            _final_text(),
        ]
    )
    agent = _echo_agent(provider, _lever_config())

    events = [event async for event in agent.run_turn("fix the bug")]

    assert any(event.kind == "done" for event in events)
    assert len(provider.calls) == 3
    second_call = _nudge_texts(provider.calls[1])
    assert len(second_call) == 1
    assert "50%" in second_call[0]
    third_call = _nudge_texts(provider.calls[2])
    assert len(third_call) == 2
    assert "50%" in third_call[0]
    assert "75%" in third_call[1]


@pytest.mark.asyncio
async def test_crossing_both_checkpoints_at_once_fires_single_nudge() -> None:
    # One long stream past 75%: both checkpoints are consumed but only the
    # latest one nudges — never two messages in the same iteration.
    provider = _SequenceProvider([[1.7, *_echo_tool_call("use-1")], _final_text()])
    agent = _echo_agent(provider, _lever_config())

    events = [event async for event in agent.run_turn("fix the bug")]

    assert any(event.kind == "done" for event in events)
    nudges = _nudge_texts(provider.calls[1])
    assert len(nudges) == 1
    assert "75%" in nudges[0]


@pytest.mark.asyncio
async def test_nudge_suppressed_by_captured_diff_candidates() -> None:
    ctx = ToolContext(
        is_owner=True,
        caller_kind=CallerKind.CLI,
        session_key="agent:main:test",
        source_diff_candidates=[{"candidate_id": "srcdiff-1", "paths": ["pkg.py"]}],
    )
    provider = _SequenceProvider([[1.2, *_echo_tool_call("use-1")], _final_text()])
    agent = _echo_agent(provider, _lever_config(), tool_context=ctx)

    events = [event async for event in agent.run_turn("fix the bug")]

    assert any(event.kind == "done" for event in events)
    assert all(_nudge_texts(call) == [] for call in provider.calls)


@pytest.mark.asyncio
async def test_nudge_suppressed_by_live_workspace_diff(tmp_path: Path) -> None:
    # Shell-made edits leave no receipts or candidates; the live workspace
    # diff must still count as change evidence.
    repo = tmp_path / "workspace"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "agent@test.invalid"],
        check=True,
    )
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "agent"], check=True)
    target = repo / "pkg.py"
    target.write_text("value = 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "init"], check=True)
    target.write_text("value = 2\n", encoding="utf-8")
    ctx = ToolContext(
        is_owner=True,
        caller_kind=CallerKind.CLI,
        session_key="agent:main:test",
        workspace_dir=str(repo),
    )
    provider = _SequenceProvider([[1.2, *_echo_tool_call("use-1")], _final_text()])
    agent = _echo_agent(provider, _lever_config(), tool_context=ctx)

    events = [event async for event in agent.run_turn("fix the bug")]

    assert any(event.kind == "done" for event in events)
    assert all(_nudge_texts(call) == [] for call in provider.calls)


@pytest.mark.asyncio
async def test_nudge_noops_without_wall_clock_budget() -> None:
    # timeout=0 means no total deadline; there is no budget fraction to
    # nudge against, so the lever must stay silent instead of dividing by
    # zero or guessing.
    provider = _SequenceProvider([_echo_tool_call("use-1"), _final_text()])
    agent = _echo_agent(provider, _lever_config(timeout=0.0))

    events = [event async for event in agent.run_turn("fix the bug")]

    assert any(event.kind == "done" for event in events)
    assert all(_nudge_texts(call) == [] for call in provider.calls)


def test_env_plumbing_for_mid_budget_nudge(monkeypatch: pytest.MonkeyPatch) -> None:
    # Helper-level check only; the full env -> bootstrap-stage -> AgentConfig
    # threading is covered in turn_runner/test_agent_bootstrap_stage_unit.py.
    from opensquilla.engine.turn_runner.agent_bootstrap_stage import _bool_from_env

    monkeypatch.delenv("OPENSQUILLA_MID_BUDGET_NO_DIFF_NUDGE", raising=False)
    assert _bool_from_env("OPENSQUILLA_MID_BUDGET_NO_DIFF_NUDGE", False) is False
    monkeypatch.setenv("OPENSQUILLA_MID_BUDGET_NO_DIFF_NUDGE", "1")
    assert _bool_from_env("OPENSQUILLA_MID_BUDGET_NO_DIFF_NUDGE", False) is True


def test_agent_config_default_keeps_lever_off() -> None:
    assert AgentConfig().mid_budget_no_diff_nudge is False
