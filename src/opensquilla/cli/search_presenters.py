"""CLI presenters for search command output."""

from __future__ import annotations

from pathlib import Path
from typing import Any, NoReturn

import typer
from rich.console import Console
from rich.table import Table

from opensquilla.cli.output import print_json
from opensquilla.cli.ui import console as ui_console
from opensquilla.cli.ui import warning_panel
from opensquilla.onboarding.search_specs import SearchProviderSetupSpec


def emit_search_provider_catalog_payload(payload: list[dict[str, object]]) -> None:
    """Emit search provider catalog JSON."""

    print_json(payload)


def emit_search_provider_setup_specs(specs: list[SearchProviderSetupSpec]) -> None:
    """Emit search provider setup specs as a human-readable table."""

    console = Console(width=160, force_terminal=False)
    table = Table(title="Search providers")
    table.add_column("provider", no_wrap=True)
    table.add_column("label", no_wrap=True)
    table.add_column("runtime", no_wrap=True)
    table.add_column("requires key", no_wrap=True)
    table.add_column("env key")
    for spec in specs:
        table.add_row(
            spec.provider_id,
            spec.label,
            "supported" if spec.runtime_supported else "unsupported (disabled)",
            "yes" if spec.requires_api_key else "no",
            spec.env_key or "-",
        )
    console.print(table)


def emit_search_status(payload: dict[str, Any], *, json_output: bool) -> None:
    """Emit runtime search provider diagnostics."""

    if json_output:
        print_json(payload)
        return

    console = Console(width=140, force_terminal=False)
    table = Table(title="Search status")
    table.add_column("provider", no_wrap=True)
    table.add_column("active", no_wrap=True)
    table.add_column("configured", no_wrap=True)
    table.add_column("buildable", no_wrap=True)
    table.add_column("fallback")
    table.add_column("error")
    table.add_row(
        str(payload.get("provider") or ""),
        "yes" if payload.get("provider") == payload.get("activeProvider") else "no",
        "yes" if payload.get("configured") else "no",
        "yes" if payload.get("buildable") else "no",
        str(payload.get("fallbackPolicy") or ""),
        str(payload.get("error") or ""),
    )
    console.print(table)


def emit_search_query_result(
    query: str,
    payload: dict[str, Any],
    *,
    json_output: bool,
) -> None:
    """Emit diagnostic search query output."""

    if json_output:
        print_json(payload)
        if not payload.get("ok", False):
            raise typer.Exit(1)
        return

    if not payload.get("ok", False):
        error = payload.get("error") or {}
        message = error.get("message") if isinstance(error, dict) else str(error)
        typer.secho(f"Search failed: {message}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    console = Console(width=160, force_terminal=False)
    table = Table(title=f"Search: {query}")
    table.add_column("Title")
    table.add_column("URL")
    table.add_column("Snippet")
    for row in payload.get("results", []):
        table.add_row(
            str(row.get("title") or ""),
            str(row.get("url") or ""),
            str(row.get("snippet") or "")[:100],
        )
    console.print(table)


def emit_search_provider_configured(
    provider: str,
    *,
    config_path: Path,
    backup_path: Path | None,
    warnings: list[str],
) -> None:
    """Emit successful search provider configuration output."""

    typer.echo(f"Search provider configured: {provider}")
    typer.echo(f"Config: {config_path}")
    for warning in warnings:
        ui_console.print(warning_panel(warning))
    if backup_path:
        typer.echo(f"Backup: {backup_path}")


def emit_search_configure_error(exc: Exception) -> NoReturn:
    """Emit search configuration errors and exit with CLI validation status."""

    typer.secho(f"Error: {exc}", fg=typer.colors.RED, err=True)
    raise typer.Exit(code=2) from exc
