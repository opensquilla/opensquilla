"""CLI workflows for session commands."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import typer

from opensquilla.cli.sessions_gateway_queries import (
    SessionGatewayActionFailed,
    SessionGatewayUnavailable,
    abort_session_from_gateway,
    delete_session_from_gateway,
    list_sessions_from_gateway,
    load_session_export_from_gateway,
    load_session_preview_from_gateway,
    resolve_session_key_from_gateway,
)
from opensquilla.cli.sessions_presenters import (
    confirm_session_delete,
    emit_session_abort,
    emit_session_delete,
    emit_session_export_empty,
    emit_session_export_error,
    emit_session_export_format_error,
    emit_session_export_unavailable,
    emit_session_exported,
    emit_session_preview,
    emit_session_resume_error,
    emit_session_resume_unavailable,
    emit_sessions_list,
    write_session_export,
)


def _parse_since(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    try:
        if raw.isdigit():
            number = float(int(raw))
            if number > 10_000_000_000:
                number = number / 1000
            return datetime.fromtimestamp(number, tz=UTC)
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed
    except ValueError as exc:
        raise typer.BadParameter("--since must be an ISO date/datetime or epoch timestamp") from exc


def _row_datetime(row: dict[str, Any]) -> datetime | None:
    value = row.get("updated_at", row.get("updatedAt"))
    if value is None:
        return None
    if isinstance(value, (int, float)):
        timestamp = float(value)
        if timestamp > 10_000_000_000:
            timestamp = timestamp / 1000
        return datetime.fromtimestamp(timestamp, tz=UTC)
    if isinstance(value, str):
        try:
            if value.isdigit():
                return _parse_since(value)
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            return parsed
        except ValueError:
            return None
    return None


def _filter_sessions(
    rows: list[dict[str, Any]],
    *,
    agent: str | None,
    status: str | None,
    channel: str | None,
    since: datetime | None,
) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for row in rows:
        if agent and str(row.get("agent_id") or row.get("agentId") or "") != agent:
            continue
        if status and str(row.get("status") or "").lower() != status.lower():
            continue
        if channel:
            channel_values = {
                str(row.get("channel") or ""),
                str(row.get("last_channel") or ""),
                str(row.get("lastChannel") or ""),
                str(row.get("source_channel") or ""),
                str(row.get("sourceChannel") or ""),
            }
            if channel not in channel_values:
                continue
        if since:
            updated = _row_datetime(row)
            if updated is None or updated < since:
                continue
        filtered.append(row)
    return filtered


def list_sessions_for_cli(
    *,
    limit: int,
    agent: str | None,
    status: str | None,
    channel: str | None,
    since: str | None,
    json_output: bool,
) -> None:
    """Load, filter, and emit recent sessions for the CLI."""

    since_dt = _parse_since(since)
    payload = list_sessions_from_gateway(limit=limit, json_output=json_output)
    raw_rows = payload.get("sessions", [])
    rows = _filter_sessions(
        [row for row in raw_rows if isinstance(row, dict)],
        agent=agent,
        status=status,
        channel=channel,
        since=since_dt,
    )
    emit_sessions_list(payload, rows, json_output=json_output)


def show_session_for_cli(session_id: str, *, json_output: bool) -> None:
    """Load and emit a single session preview for the CLI."""

    payload = load_session_preview_from_gateway(session_id, json_output=json_output)
    emit_session_preview(payload, session_id=session_id, json_output=json_output)


def resume_session_for_cli(session_id: str) -> None:
    """Resolve a session and resume it in interactive chat."""

    result = resolve_session_key_from_gateway(session_id)
    if isinstance(result, SessionGatewayUnavailable):
        emit_session_resume_unavailable(session_id, message=result.message)
        return
    if isinstance(result, SessionGatewayActionFailed):
        emit_session_resume_error(result.message)
        return

    from opensquilla.cli.chat_cmd import run_chat

    run_chat(session_id=result)


def export_session_for_cli(
    session_id: str,
    *,
    output: Path | None,
    format: str,
) -> None:
    """Load, write, and emit a session export for the CLI."""

    if format not in {"md", "json"}:
        emit_session_export_format_error()

    payload = load_session_export_from_gateway(session_id)
    if isinstance(payload, SessionGatewayUnavailable):
        emit_session_export_unavailable(payload.message)
        return
    if isinstance(payload, SessionGatewayActionFailed):
        emit_session_export_error(payload.message)
        return
    if payload is None:
        emit_session_export_empty()
        return

    target = write_session_export(payload, session_id=session_id, output=output, format=format)
    emit_session_exported(target)


def abort_session_for_cli(session_id: str, *, json_output: bool) -> None:
    """Resolve, abort, and emit a session abort result for the CLI."""

    payload = abort_session_from_gateway(session_id, json_output=json_output)
    emit_session_abort(payload, session_id=session_id, json_output=json_output)


def delete_session_for_cli(session_id: str, *, yes: bool) -> None:
    """Confirm, delete, and emit a session deletion result for the CLI."""

    confirm_session_delete(session_id, yes=yes)
    payload = delete_session_from_gateway(session_id)
    emit_session_delete(payload)
