"""CLI presenters for session output."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, NoReturn

import typer
from rich.table import Table

from opensquilla.cli.output import print_json
from opensquilla.cli.repl.session_state import messages_to_markdown
from opensquilla.cli.ui import console, error_panel


def emit_sessions_list(
    payload: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    json_output: bool,
) -> None:
    """Emit filtered session rows."""

    if json_output:
        json_payload = dict(payload)
        json_payload["sessions"] = rows
        json_payload["count"] = len(rows)
        print_json(json_payload)
        return

    table = Table(title="Sessions", show_header=True, header_style="bold cyan")
    table.add_column("Key")
    table.add_column("Agent")
    table.add_column("Status")
    table.add_column("Model")
    table.add_column("Messages", justify="right")
    for row in rows:
        table.add_row(
            str(row.get("key") or ""),
            str(row.get("agent_id") or row.get("agentId") or ""),
            str(row.get("status") or ""),
            str(row.get("model") or ""),
            str(row.get("message_count") or row.get("entry_count") or 0),
        )
    console.print(table)


def _resolved_key(payload: dict[str, Any], fallback: str) -> str:
    value = payload.get("session_key") or payload.get("key") or fallback
    return str(value)


def emit_session_preview(
    payload: dict[str, Any],
    *,
    session_id: str,
    json_output: bool,
) -> None:
    """Emit resolved session metadata and preview."""

    if json_output:
        print_json(payload)
        return

    resolved = payload.get("resolved", {})
    if not isinstance(resolved, dict):
        resolved = {}
    preview_payload = payload.get("preview", {})
    previews = preview_payload.get("previews", []) if isinstance(preview_payload, dict) else []
    preview = previews[0] if previews else {}
    if not isinstance(preview, dict):
        preview = {}

    key = _resolved_key(resolved, session_id)
    table = Table(title=f"Session {key}", show_header=True, header_style="bold cyan")
    table.add_column("Field", style="cyan")
    table.add_column("Value")
    for field, value in (
        ("session_key", key),
        ("session_id", resolved.get("session_id")),
        ("agent_id", resolved.get("agent_id")),
        ("status", resolved.get("status")),
        ("model", resolved.get("model")),
        ("updated_at", resolved.get("updated_at") or preview.get("updatedAt")),
        ("title", preview.get("title")),
    ):
        if value not in (None, ""):
            table.add_row(field, str(value))
    console.print(table)
    last_message = str(preview.get("lastMessage") or "")
    if last_message:
        console.print(last_message)


def emit_session_resume_unavailable(session_id: str, *, message: str) -> None:
    """Emit resume's gateway-unavailable message."""

    if message:
        console.print(f"[dim]{message}[/dim]")
    console.print(f"[dim]Session {session_id!r} requires a running gateway.[/dim]")


def emit_session_resume_error(message: str) -> None:
    """Emit resume's gateway action failure message."""

    console.print(error_panel(message))


def emit_session_export_format_error() -> NoReturn:
    """Emit invalid export format and exit with validation status."""

    console.print("[red]--format must be md or json[/red]")
    raise typer.Exit(2)


def emit_session_export_unavailable(message: str) -> None:
    """Emit export's gateway-unavailable message."""

    if message:
        console.print(f"[dim]{message}[/dim]")
    console.print("[dim]Session export requires a running gateway.[/dim]")


def emit_session_export_error(message: str) -> None:
    """Emit export's gateway action failure message."""

    console.print(error_panel(message))


def emit_session_export_empty() -> None:
    """Emit empty export payload message."""

    console.print("[red]Session export returned no data.[/red]")


def _render_session_export_markdown(payload: dict[str, Any], *, session_id: str) -> str:
    resolved = payload.get("resolved", {})
    if not isinstance(resolved, dict):
        resolved = {}
    key = _resolved_key(resolved, session_id)
    preview_payload = payload.get("preview", {})
    previews = preview_payload.get("previews", []) if isinstance(preview_payload, dict) else []
    preview = previews[0] if previews else {}
    if not isinstance(preview, dict):
        preview = {}
    history_payload = payload.get("history", {})
    messages = history_payload.get("messages", []) if isinstance(history_payload, dict) else []
    transcript = messages_to_markdown(messages) if isinstance(messages, list) else ""
    if not transcript.strip():
        transcript = f"## Preview\n\n{preview.get('lastMessage', '')}\n"
    return (
        f"# Session {key}\n\n"
        f"- Status: {resolved.get('status', '')}\n"
        f"- Model: {resolved.get('model') or ''}\n"
        f"- Updated: {resolved.get('updated_at', '')}\n\n"
        f"{transcript}"
    )


def write_session_export(
    payload: dict[str, Any],
    *,
    session_id: str,
    output: Path | None,
    format: str,
) -> Path:
    """Write a session export payload to disk and return the target path."""

    target = output or Path(f"{session_id.replace(':', '-')}.{format}")
    if format == "json":
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        target.write_text(
            _render_session_export_markdown(payload, session_id=session_id),
            encoding="utf-8",
        )
    return target


def emit_session_exported(target: Path) -> None:
    """Emit successful session export output."""

    console.print(f"[green]Exported:[/green] {target}")


def emit_session_abort(
    payload: dict[str, Any],
    *,
    session_id: str,
    json_output: bool,
) -> None:
    """Emit session abort result."""

    if json_output:
        print_json(payload)
        return

    key = payload.get("key") or session_id
    aborted = bool(payload.get("aborted", False))
    console.print(f"{'Aborted' if aborted else 'No running task for'} session {key!r}")


def confirm_session_delete(session_id: str, *, yes: bool) -> None:
    """Confirm destructive session deletion unless already approved."""

    if not yes:
        typer.confirm(f"Delete session {session_id!r}?", abort=True)


def emit_session_delete(payload: dict[str, Any]) -> None:
    """Emit session deletion result."""

    console.print_json(data=payload)
