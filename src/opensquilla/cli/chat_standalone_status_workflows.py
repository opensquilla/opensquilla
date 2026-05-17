"""Standalone status slash-command workflows for interactive chat."""

from __future__ import annotations

from opensquilla.cli.repl.session_state import ChatSessionState
from opensquilla.cli.ui import ACCENT, console


def handle_standalone_status_command(state: ChatSessionState) -> None:
    """Handle the standalone chat /status and /session commands."""

    console.print(
        f"[{ACCENT}]session[/] [dim]{state.session_key}[/dim]\n"
        f"[{ACCENT}]model[/] [dim]{state.model or 'default'}[/dim]"
    )


def handle_standalone_models_command() -> None:
    """Handle the standalone chat /models command."""

    console.print("[yellow]/models requires gateway mode.[/yellow]")
