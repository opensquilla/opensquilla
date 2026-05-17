"""Session maintenance slash-command workflows for interactive gateway chat."""

from __future__ import annotations

from typing import Any, Protocol

from opensquilla.cli.repl.session_state import ChatSessionState
from opensquilla.cli.ui import ACCENT, console


class SessionMaintenanceClient(Protocol):
    async def reset_session(self, key: str) -> dict[str, Any]: ...

    async def compact_session(self, key: str) -> dict[str, Any]: ...


async def handle_clear_session_command(
    state: ChatSessionState,
    client: SessionMaintenanceClient,
) -> None:
    """Handle the gateway chat /clear and /reset commands."""

    await client.reset_session(state.session_key)
    state.transcript.clear()
    state.usage.reset()
    console.print(f"[{ACCENT}]cleared[/] [dim]{state.session_key}[/dim]")


async def handle_compact_session_command(
    state: ChatSessionState,
    client: SessionMaintenanceClient,
) -> None:
    """Handle the gateway chat /compact command."""

    payload = await client.compact_session(state.session_key)
    if payload.get("compacted"):
        console.print(
            f"[{ACCENT}]compacted[/] "
            f"[dim]summary {payload.get('summary_len', 0)} chars[/dim]"
        )
    else:
        console.print(f"[{ACCENT}]compact skipped[/] [dim]context already within budget[/dim]")
