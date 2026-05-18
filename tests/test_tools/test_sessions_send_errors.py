from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from opensquilla.engine.types import ToolCall
from opensquilla.tools.builtin import sessions as sessions_tools
from opensquilla.tools.dispatch import build_tool_handler
from opensquilla.tools.registry import ToolRegistry
from opensquilla.tools.types import ToolSpec


class _TerminalSessionManager:
    async def get_session(self, session_key: str) -> object:
        return SimpleNamespace(session_key=session_key, status="done")


def _sessions_send_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="sessions_send",
            description="send",
            parameters={
                "session_key": {"type": "string"},
                "message": {"type": "string"},
            },
            required=["session_key", "message"],
        ),
        sessions_tools.sessions_send,
    )
    return registry


@pytest.mark.asyncio
async def test_sessions_send_terminal_session_error_is_user_actionable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sessions_tools, "_session_manager", _TerminalSessionManager())

    handler = build_tool_handler(_sessions_send_registry())
    result = await handler(
        ToolCall(
            tool_use_id="tc-sessions-send-terminal",
            tool_name="sessions_send",
            arguments={
                "session_key": "agent:main:subagent:done",
                "message": "hello",
            },
        )
    )

    assert result.is_error is True
    payload = json.loads(result.content)
    assert payload["error_class"] == "SafeToolError"
    assert "terminated" in payload["user_message"]
    assert "internal error" not in payload["user_message"]
