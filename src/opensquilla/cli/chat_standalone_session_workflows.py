"""Standalone session slash-command workflows for interactive chat."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any
from uuid import uuid4

from opensquilla.cli.repl.session_state import ChatSessionState
from opensquilla.cli.ui import console


async def handle_standalone_new_command(
    parts: Sequence[str],
    *,
    session_manager: Any,
    build_tool_context: Callable[[str], object],
    model: str | None,
) -> tuple[str, object, ChatSessionState]:
    """Handle standalone chat /new by creating a fresh session and state."""

    session_key = f"agent:main:standalone:{uuid4().hex[:8]}"
    await session_manager.get_or_create(session_key, agent_id="main")
    tool_context = build_tool_context(session_key)
    state = ChatSessionState(session_key=session_key, model=model)
    title = parts[1].strip() if len(parts) > 1 else None
    label = f" ({title})" if title else ""
    console.print(f"[green]Started new session{label}:[/green] {session_key}")
    return session_key, tool_context, state
