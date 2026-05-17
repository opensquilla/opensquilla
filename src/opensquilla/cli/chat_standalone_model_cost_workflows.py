"""Standalone model and cost slash-command workflows for interactive chat."""

from __future__ import annotations

from opensquilla.cli.repl.session_state import ChatSessionState
from opensquilla.cli.ui import console


def handle_standalone_model_command(
    parts: list[str],
    state: ChatSessionState,
) -> str | None:
    """Handle the standalone chat /model command.

    Returns the new model when the caller must update its local model variable.
    """

    if len(parts) == 1:
        console.print(f"[dim]model={state.model or 'default'}[/dim]")
        return None

    model = parts[1].strip()
    state.model = model
    console.print(f"[green]model:[/green] {model}")
    return model


def handle_standalone_cost_command(state: ChatSessionState) -> None:
    """Handle the standalone chat /cost command."""

    console.print(state.usage.render())
