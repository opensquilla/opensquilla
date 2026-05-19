"""CLI presenters for durable memory RPC output."""

from __future__ import annotations

from typing import Any

from rich.table import Table

from opensquilla.cli.output import print_json
from opensquilla.cli.ui import console


def emit_memory_status(
    payload: dict[str, Any],
    *,
    agent_id: str,
    json_output: bool,
) -> None:
    """Emit memory backend status."""

    if json_output:
        print_json(payload)
        return

    table = Table(title=f"Memory status — agent={agent_id}", show_header=True)
    table.add_column("Backend")
    table.add_column("Status")
    table.add_column("Entries", justify="right")
    table.add_column("Size bytes", justify="right")
    table.add_column("Error")
    table.add_row(
        str(payload.get("backend") or ""),
        str(payload.get("status") or ""),
        "" if payload.get("entryCount") is None else str(payload.get("entryCount")),
        "" if payload.get("sizeBytes") is None else str(payload.get("sizeBytes")),
        str(payload.get("error") or ""),
    )
    console.print(table)


def emit_memory_sources(
    payload: dict[str, Any],
    *,
    agent_id: str,
    json_output: bool,
) -> None:
    """Emit durable memory source files."""

    if json_output:
        print_json(payload)
        return

    table = Table(title=f"Memory sources - agent={agent_id}", show_header=True)
    table.add_column("Path")
    table.add_column("Lines", justify="right")
    table.add_column("Size bytes", justify="right")
    table.add_column("Modified")
    for row in payload.get("files", []):
        table.add_row(
            str(row.get("path") or ""),
            "" if row.get("lineCount") is None else str(row.get("lineCount")),
            "" if row.get("sizeBytes") is None else str(row.get("sizeBytes")),
            str(row.get("modifiedAt") or ""),
        )
    console.print(table)


def emit_memory_search_results(
    payload: dict[str, Any],
    *,
    agent_id: str,
    json_output: bool,
) -> None:
    """Emit durable memory search results."""

    if json_output:
        print_json(payload)
        return

    table = Table(title=f"Memory search - agent={agent_id}", show_header=True)
    table.add_column("Path")
    table.add_column("Lines")
    table.add_column("Score", justify="right")
    table.add_column("Snippet")
    for row in payload.get("results", []):
        table.add_row(
            str(row.get("path") or ""),
            f"{row.get('startLine', '')}-{row.get('endLine', '')}",
            f"{float(row.get('score') or 0.0):.3f}",
            str(row.get("snippet") or "")[:120],
        )
    console.print(table)


def emit_memory_source_content(
    payload: dict[str, Any],
    *,
    json_output: bool,
) -> None:
    """Emit durable memory source content."""

    if json_output:
        print_json(payload)
        return

    console.print(str(payload.get("content") or ""))
    if payload.get("truncated"):
        console.print("[dim]... truncated[/dim]")
