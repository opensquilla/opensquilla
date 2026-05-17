"""Gateway help slash-command workflow for interactive chat."""

from __future__ import annotations

from opensquilla.cli.repl.commands import render_help_table
from opensquilla.cli.ui import console


def handle_gateway_help_command() -> None:
    """Handle the gateway chat /help command."""
    console.print(render_help_table())
