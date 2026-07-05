"""Model catalog CLI commands."""

from __future__ import annotations

from typing import Any, cast

import typer
from rich.table import Table

from opensquilla.cli.gateway_rpc import run_gateway_sync
from opensquilla.cli.output import print_json
from opensquilla.cli.ui import ACCENT_HEADER, console, error_console, markup_escape

app = typer.Typer(help="Inspect available models.")


@app.command("list")
def models_list(
    provider: str | None = typer.Option(None, "--provider", help="Provider filter"),
    capability: list[str] | None = typer.Option(
        None, "--capability", "-c", help="Required capability"
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """List available models from the running gateway."""

    async def _with_client(client) -> Any:
        return await client.call(
            "models.list", {"provider": provider, "capabilities": capability}
        )

    payload = run_gateway_sync(_with_client, json_output=json_output)
    if isinstance(payload, list):
        # Pre-envelope gateways returned the bare row list.
        rows = cast(list[dict[str, Any]], payload)
        errors: list[dict[str, Any]] = []
    else:
        rows = cast(list[dict[str, Any]], list(payload.get("models") or []))
        errors = cast(list[dict[str, Any]], list(payload.get("errors") or []))

    if json_output:
        print_json(rows)
        return

    table = Table(title="Models", show_header=True, header_style=ACCENT_HEADER)
    table.add_column("ID")
    table.add_column("Provider")
    table.add_column("Context", justify="right")
    table.add_column("Capabilities")
    table.add_column("Input/1k", justify="right")
    table.add_column("Output/1k", justify="right")
    for row in rows:
        pricing = row.get("pricing") or {}
        table.add_row(
            str(row.get("id") or ""),
            str(row.get("provider") or ""),
            str(row.get("contextWindow") or ""),
            ", ".join(str(v) for v in row.get("capabilities") or []),
            str(pricing.get("inputPer1k") or ""),
            str(pricing.get("outputPer1k") or ""),
        )
    console.print(table)

    if errors:
        error_console.print("[yellow]Some providers failed to list models:[/yellow]")
        for err in errors:
            provider_id = markup_escape(str(err.get("provider") or "unknown"))
            kind = markup_escape(str(err.get("kind") or "unknown"))
            detail = markup_escape(str(err.get("detail") or ""))
            line = f"  - {provider_id}: {kind}"
            if detail:
                line += f" — {detail}"
            error_console.print(f"[yellow]{line}[/yellow]")
