"""Typed bridge from REPL runtimes to the terminal TUI adapter."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from opensquilla.cli.tui.adapters.terminal_chat_adapter import (
    ChatRuntimeScope,
    clear_current_cancel,
    get_tui_output,
    run_terminal_chat_runtime,
)
from opensquilla.engine.commands import Surface


async def run_concurrent_repl(
    *,
    surface: Surface,
    scope: ChatRuntimeScope,
    dispatch: Callable[[str], Awaitable[bool]],
    queue_max_size: int,
    abort_active_turn: Callable[[], Awaitable[None]] | None = None,
) -> None:
    """Run terminal chat without exposing concrete TUI adapters to chat_cmd."""
    await run_terminal_chat_runtime(
        surface=surface,
        scope=scope,
        dispatch=dispatch,
        queue_max_size=queue_max_size,
        abort_active_turn=abort_active_turn,
    )


__all__ = [
    "ChatRuntimeScope",
    "clear_current_cancel",
    "get_tui_output",
    "run_concurrent_repl",
]
