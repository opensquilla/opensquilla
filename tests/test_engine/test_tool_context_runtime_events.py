from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from typing import Any

from opensquilla.engine import Agent, AgentConfig
from opensquilla.sandbox.config import SandboxSettings
from opensquilla.sandbox.integration import configure_runtime, reset_runtime
from opensquilla.tool_boundary import ToolCall
from opensquilla.tools.dispatch import build_tool_handler
from opensquilla.tools.registry import ToolRegistry, get_default_registry
from opensquilla.tools.types import (
    InteractionMode,
    ToolContext,
    ToolSpec,
    current_tool_context,
)


class _Provider:
    provider_name = "fake"

    def chat(self, messages, tools=None, config=None):
        raise AssertionError("provider should not be used")

    async def list_models(self) -> list[Any]:
        return []


def test_agent_wires_tool_context_runtime_events(tmp_path) -> None:
    runtime_events_path = tmp_path / "runtime_events.jsonl"
    agent = Agent(
        provider=_Provider(),
        config=AgentConfig(
            runtime_events_path=str(runtime_events_path),
            metadata={"agent_id": "configured-agent"},
        ),
        session_key="agent-session",
        tool_context=ToolContext(),
    )

    assert agent._tool_context is not None
    assert agent._tool_context.on_runtime_event is not None

    agent._tool_context.on_runtime_event(
        {
            "feature": "fresh_read_guard",
            "name": "fresh_read_guard.blocked",
            "tool": "edit_file",
            "outcome": "blocked",
        }
    )

    events = [
        json.loads(line)
        for line in runtime_events_path.read_text(encoding="utf-8").splitlines()
    ]
    assert len(events) == 1
    assert events[0]["feature"] == "fresh_read_guard"
    assert events[0]["name"] == "fresh_read_guard.blocked"
    assert events[0]["tool"] == "edit_file"
    assert events[0]["outcome"] == "blocked"
    assert events[0]["session_key"] == "agent-session"
    assert events[0]["agent_id"] == "configured-agent"
    assert "created_at" in events[0]
    assert "timestamp" in events[0]


def test_agent_preserves_tool_context_runtime_event_identity(tmp_path) -> None:
    runtime_events_path = tmp_path / "runtime_events.jsonl"
    agent = Agent(
        provider=_Provider(),
        config=AgentConfig(
            runtime_events_path=str(runtime_events_path),
            metadata={"agent_id": "configured-agent"},
        ),
        session_key="agent-session",
        tool_context=ToolContext(),
    )

    assert agent._tool_context is not None
    assert agent._tool_context.on_runtime_event is not None

    agent._tool_context.on_runtime_event(
        {
            "feature": "fresh_read_guard",
            "name": "fresh_read_guard.blocked",
            "agent_id": "tool-agent",
            "session_key": "tool-session",
            "outcome": "blocked",
        }
    )

    event = json.loads(runtime_events_path.read_text(encoding="utf-8"))
    assert event["agent_id"] == "tool-agent"
    assert event["session_key"] == "tool-session"


def test_agent_backfills_none_tool_context_runtime_event_identity(tmp_path) -> None:
    runtime_events_path = tmp_path / "runtime_events.jsonl"
    agent = Agent(
        provider=_Provider(),
        config=AgentConfig(
            runtime_events_path=str(runtime_events_path),
            metadata={"agent_id": "configured-agent"},
        ),
        session_key="agent-session",
        tool_context=ToolContext(),
    )

    assert agent._tool_context is not None
    assert agent._tool_context.on_runtime_event is not None

    agent._tool_context.on_runtime_event(
        {
            "feature": "fresh_read_guard",
            "name": "fresh_read_guard.blocked",
            "agent_id": None,
            "session_key": None,
            "outcome": "blocked",
        }
    )

    event = json.loads(runtime_events_path.read_text(encoding="utf-8"))
    assert event["agent_id"] == "configured-agent"
    assert event["session_key"] == "agent-session"


def test_agent_runtime_event_callback_reaches_prebuilt_tool_handler(tmp_path) -> None:
    runtime_events_path = tmp_path / "runtime_events.jsonl"
    ctx = ToolContext()
    registry = ToolRegistry()

    async def emit_event() -> str:
        active = current_tool_context.get()
        assert active is ctx
        assert active.on_runtime_event is not None
        active.on_runtime_event(
            {
                "feature": "tool_runtime",
                "name": "tool_runtime.probe",
                "outcome": "used",
            }
        )
        return "ok"

    registry.register(
        ToolSpec(
            name="emit_event",
            description="Emit a runtime event.",
            parameters={},
            required=[],
        ),
        emit_event,
    )
    handler = build_tool_handler(registry, ctx)

    agent = Agent(
        provider=_Provider(),
        config=AgentConfig(
            runtime_events_path=str(runtime_events_path),
            metadata={"agent_id": "configured-agent"},
        ),
        tool_handler=handler,
        session_key="agent-session",
        tool_context=ctx,
    )

    assert agent._tool_context is ctx
    assert ctx.on_runtime_event is not None

    import asyncio

    result = asyncio.run(handler(ToolCall("call-1", "emit_event", {})))
    assert result.content == "ok"

    event = json.loads(runtime_events_path.read_text(encoding="utf-8"))
    assert event["feature"] == "tool_runtime"
    assert event["name"] == "tool_runtime.probe"
    assert event["agent_id"] == "configured-agent"
    assert event["session_key"] == "agent-session"


def test_agent_runtime_event_context_reaches_replaced_builtin_tool_handler(
    tmp_path,
) -> None:
    runtime_events_path = tmp_path / "runtime_events.jsonl"
    target = tmp_path / "src" / "app.py"
    target.parent.mkdir()
    target.write_text(
        "def run():\n"
        "    if enabled:\n"
        "        return 1\n",
        encoding="utf-8",
    )

    configure_runtime(
        SandboxSettings(
            sandbox=False,
            security_grading=False,
            allow_legacy_mode=True,
        ),
        workspace=tmp_path,
    )
    try:
        handler_ctx = ToolContext(
            is_owner=True,
            interaction_mode=InteractionMode.UNATTENDED,
            workspace_dir=str(tmp_path),
            elevated="bypass",
        )
        handler = build_tool_handler(get_default_registry(), handler_ctx)
        agent_ctx = replace(handler_ctx, session_key="agent-session")
        agent = Agent(
            provider=_Provider(),
            config=AgentConfig(
                runtime_events_path=str(runtime_events_path),
                metadata={"agent_id": "configured-agent"},
            ),
            tool_handler=handler,
            session_key="agent-session",
            tool_context=agent_ctx,
        )

        assert agent.tool_handler is not None
        result = asyncio.run(
            agent.tool_handler(
                ToolCall(
                    "call-1",
                    "edit_file",
                    {
                        "path": str(target),
                        "old_text": "if enabled:\n    return 1\n",
                        "new_text": "if enabled:\n    return 2\n",
                    },
                )
            )
        )
    finally:
        reset_runtime()

    assert result.is_error is False
    events = [
        json.loads(line)
        for line in runtime_events_path.read_text(encoding="utf-8").splitlines()
    ]
    assert any(event["name"] == "edit_file.flexible_match_used" for event in events)
    assert events[0]["agent_id"] == "main"
    assert events[0]["session_key"] == "agent-session"
