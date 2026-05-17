"""CLI presenters for session output."""

from __future__ import annotations

from typing import Any

from rich.table import Table

from opensquilla.cli.output import print_json
from opensquilla.cli.ui import console


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
