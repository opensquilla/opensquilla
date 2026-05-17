"""CLI workflows for session commands."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import typer

from opensquilla.cli.sessions_gateway_queries import (
    list_sessions_from_gateway,
    load_session_preview_from_gateway,
)
from opensquilla.cli.sessions_presenters import (
    emit_session_preview,
    emit_sessions_list,
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
