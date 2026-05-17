"""Presentation helpers for CLI skill catalog commands."""

from __future__ import annotations

from typing import Any

from rich.table import Table

from opensquilla.cli.output import print_json
from opensquilla.cli.ui import console


def emit_skill_rows(rows: list[dict[str, Any]], *, json_output: bool) -> None:
    """Emit installed and available skill rows."""

    if json_output:
        print_json(rows)
        return

    table = Table(title=f"Skills ({len(rows)})")
    table.add_column("Name", style="cyan")
    table.add_column("Layer")
    table.add_column("Eligible")
    table.add_column("Description")

    for row in rows:
        description = str(row["description"])
        table.add_row(
            str(row["name"]),
            str(row["layer"]),
            "[green]yes[/]" if row["eligible"] else "[dim]no[/]",
            description[:60] + "..." if len(description) > 60 else description,
        )
    console.print(table)


def emit_skill_search_results(
    query: str,
    results: list[dict[str, Any]],
    *,
    json_output: bool,
) -> None:
    """Emit skill search results."""

    if json_output:
        print_json(results)
        return

    if not results:
        console.print(f"[dim]No results for '{query}'[/]")
        return

    table = Table(title=f"Search: {query}")
    table.add_column("Name", style="cyan")
    table.add_column("Source")
    table.add_column("Trust")
    table.add_column("Description")

    for row in results:
        table.add_row(
            str(row["name"]),
            str(row["source_id"]),
            str(row["trust_level"]),
            str(row["description"])[:60],
        )
    console.print(table)
