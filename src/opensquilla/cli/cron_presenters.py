"""CLI presenters for cron scheduler output."""

from __future__ import annotations

from typing import Any

import typer
from rich.table import Table

from opensquilla.cli.output import print_json
from opensquilla.cli.ui import console


def cron_rows(payload: Any, *, key: str = "jobs") -> list[dict[str, Any]]:
    """Normalize cron list/runs payloads into table rows."""

    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        rows = payload.get(key, [])
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    return []


def emit_cron_jobs(payload: Any, *, json_output: bool) -> None:
    """Emit cron job rows."""

    if json_output:
        print_json(payload)
        return
    _render_jobs(cron_rows(payload))


def emit_cron_runs(payload: Any, *, json_output: bool) -> None:
    """Emit cron run rows."""

    if json_output:
        print_json(payload)
        return
    _render_runs(cron_rows(payload, key="runs"))


def emit_cron_success(payload: Any, *, json_output: bool, title: str) -> None:
    """Emit a cron action result."""

    if json_output:
        print_json(payload)
    elif isinstance(payload, dict):
        _render_mapping(payload, title=title)
    else:
        typer.echo(str(payload))


def _render_jobs(rows: list[dict[str, Any]], *, title: str = "Cron jobs") -> None:
    if not rows:
        typer.echo("No cron jobs.")
        return
    table = Table(title=title, show_header=True, header_style="bold cyan")
    table.add_column("ID")
    table.add_column("Name")
    table.add_column("Enabled")
    table.add_column("Expression")
    table.add_column("Agent")
    table.add_column("Next run")
    table.add_column("Last run")
    table.add_column("Errors", justify="right")
    for row in rows:
        table.add_row(
            str(row.get("id") or ""),
            str(row.get("name") or ""),
            str(row.get("enabled") or False),
            str(row.get("expression") or row.get("schedule_raw") or ""),
            str(row.get("agentId") or row.get("agent_id") or ""),
            str(row.get("next_run") or ""),
            str(row.get("last_run") or ""),
            str(row.get("error_count") or row.get("consecutive_errors") or 0),
        )
    console.print(table)


def _render_mapping(payload: dict[str, Any], *, title: str) -> None:
    table = Table(title=title, show_header=True, header_style="bold cyan")
    table.add_column("Field")
    table.add_column("Value")
    for key, value in payload.items():
        table.add_row(str(key), str(value))
    console.print(table)


def _render_runs(rows: list[dict[str, Any]]) -> None:
    if not rows:
        typer.echo("No cron runs.")
        return
    table = Table(title="Cron runs", show_header=True, header_style="bold cyan")
    table.add_column("ID")
    table.add_column("Started")
    table.add_column("Finished")
    table.add_column("Status")
    table.add_column("Duration ms", justify="right")
    table.add_column("Error")
    for row in rows:
        table.add_row(
            str(row.get("id") or ""),
            str(row.get("started_at") or ""),
            str(row.get("finished_at") or ""),
            str(row.get("status") or ("ok" if row.get("success") else "error")),
            str(row.get("duration_ms") or ""),
            str(row.get("error") or ""),
        )
    console.print(table)
