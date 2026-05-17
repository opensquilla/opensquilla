"""CLI presenters for config commands."""

from __future__ import annotations

from typing import Any, NoReturn

import typer
from rich.markup import escape
from rich.table import Table

from opensquilla.cli.ui import console


def emit_config_value(key: str, value: Any) -> None:
    """Emit one config value."""

    console.print(f"[cyan]{escape(key)}[/cyan] = [green]{escape(repr(value))}[/green]")


def emit_config_table(data: dict[str, Any]) -> None:
    """Emit flattened public config data."""

    table = Table(title="Gateway Config", show_header=True, header_style="bold cyan")
    table.add_column("Key")
    table.add_column("Value")
    _add_flat(table, data)
    console.print(table)


def emit_missing_config_key(key: str) -> NoReturn:
    """Emit a missing-key error and exit with CLI lookup failure status."""

    console.print(f"[red]Key not found: {key}[/red]")
    raise typer.Exit(1)


def emit_config_export_hint(key: str, value: str) -> None:
    """Emit the env-var backed config set hint."""

    env_key = "OPENSQUILLA_GATEWAY_" + key.upper().replace(".", "__")
    console.print("[dim]To persist this setting, export:[/dim]")
    console.print(f"  [bold]export {env_key}={value}[/bold]")


def _add_flat(table: Table, data: dict[str, Any], prefix: str = "") -> None:
    for key, value in data.items():
        full_key = f"{prefix}{key}" if not prefix else f"{prefix}.{key}"
        if isinstance(value, dict):
            _add_flat(table, value, full_key)
        else:
            table.add_row(escape(full_key), escape(str(value)))
