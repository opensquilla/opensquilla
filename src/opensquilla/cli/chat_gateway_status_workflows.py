"""Gateway status slash-command workflow for interactive chat."""

from __future__ import annotations

from opensquilla.cli.repl.session_state import ChatSessionState
from opensquilla.cli.ui import ACCENT, console


def handle_gateway_status_command(state: ChatSessionState) -> bool:
    """Handle gateway chat /status and /session commands."""
    console.print(
        f"[{ACCENT}]session[/] [dim]{state.session_key}[/dim]\n"
        f"[{ACCENT}]model[/] [dim]{state.model or 'default'}[/dim]\n"
        f"[{ACCENT}]permissions[/] [dim]{state.elevated or 'normal'}[/dim]"
    )
    return True
