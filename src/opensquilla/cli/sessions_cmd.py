"""Sessions command — list/show/resume/delete/export sessions."""

from __future__ import annotations

from pathlib import Path

import typer

from opensquilla.cli.sessions_workflows import (
    abort_session_for_cli,
    delete_session_for_cli,
    export_session_for_cli,
    list_sessions_for_cli,
    resume_session_for_cli,
    show_session_for_cli,
)

app = typer.Typer(help="Manage chat sessions.")


@app.command("list")
def sessions_list(
    limit: int = typer.Option(50, "--limit", "-n", help="Maximum rows"),
    agent: str | None = typer.Option(None, "--agent", help="Filter by agent id"),
    status: str | None = typer.Option(None, "--status", help="Filter by session status"),
    channel: str | None = typer.Option(None, "--channel", help="Filter by channel/source"),
    since: str | None = typer.Option(None, "--since", help="ISO date/datetime or epoch timestamp"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """List recent sessions."""
    list_sessions_for_cli(
        limit=limit,
        agent=agent,
        status=status,
        channel=channel,
        since=since,
        json_output=json_output,
    )


@app.command("show")
def sessions_show(
    session_id: str = typer.Argument(..., help="Session ID to inspect"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Show details of a specific session."""
    show_session_for_cli(session_id, json_output=json_output)


@app.command("resume")
def sessions_resume(session_id: str = typer.Argument(..., help="Session ID to resume")) -> None:
    """Resume a session in interactive chat."""
    resume_session_for_cli(session_id)


@app.command("abort")
def sessions_abort(
    session_id: str = typer.Argument(..., help="Session ID to abort"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Abort a running session turn."""
    abort_session_for_cli(session_id, json_output=json_output)


@app.command("delete")
def sessions_delete(
    session_id: str = typer.Argument(..., help="Session ID to delete"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Delete a session."""
    delete_session_for_cli(session_id, yes=yes)


@app.command("export")
def sessions_export(
    session_id: str = typer.Argument(..., help="Session ID to export"),
    output: Path | None = typer.Option(None, "--output", "-o", help="Output file"),
    format: str = typer.Option("md", "--format", help="Export format: md|json"),
) -> None:
    """Export session transcript and metadata.

    Uses the existing chat.history RPC for persisted transcript messages and
    falls back to session preview when no messages are available.
    """
    export_session_for_cli(session_id, output=output, format=format)
