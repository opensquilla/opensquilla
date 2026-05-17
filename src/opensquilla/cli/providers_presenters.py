"""CLI presenters for provider catalog output."""

from __future__ import annotations

from pathlib import Path
from typing import Any, NoReturn

import typer
from rich.console import Console
from rich.table import Table

from opensquilla.cli.output import print_json
from opensquilla.onboarding.provider_specs import ProviderSetupSpec


def emit_provider_catalog_payload(payload: list[dict[str, object]]) -> None:
    """Emit provider catalog JSON."""

    print_json(payload)


def emit_provider_setup_specs(specs: list[ProviderSetupSpec]) -> None:
    """Emit provider setup specs as a human-readable table."""

    console = Console(width=200, force_terminal=False)
    table = Table(title="Providers")
    table.add_column("provider", no_wrap=True)
    table.add_column("label", no_wrap=True)
    table.add_column("runtime", no_wrap=True)
    table.add_column("requires key", no_wrap=True)
    table.add_column("requires base url", no_wrap=True)
    table.add_column("default base url")
    for spec in specs:
        table.add_row(
            spec.provider_id,
            spec.label,
            "supported" if spec.runtime_supported else "unsupported (disabled)",
            "yes" if spec.requires_api_key else "no",
            "yes" if spec.requires_base_url else "no",
            spec.default_base_url or "-",
        )
    console.print(table)


def emit_provider_status(payload: dict[str, Any], *, json_output: bool) -> None:
    """Emit provider status diagnostics."""

    if json_output:
        print_json(payload)
        return

    console = Console(width=180, force_terminal=False)
    table = Table(title="Provider status")
    table.add_column("provider", no_wrap=True)
    table.add_column("active", no_wrap=True)
    table.add_column("configured", no_wrap=True)
    table.add_column("buildable", no_wrap=True)
    table.add_column("model")
    table.add_column("error")
    for row in payload.get("providers", []):
        table.add_row(
            str(row.get("providerId") or ""),
            "yes" if row.get("active") else "no",
            "yes" if row.get("configured") else "no",
            "yes" if row.get("buildable") else "no",
            str(row.get("model") or ""),
            str(row.get("error") or ""),
        )
    console.print(table)


def emit_provider_configured(
    provider: str,
    *,
    config_path: Path,
    backup_path: Path | None,
) -> None:
    """Emit successful provider configuration output."""

    typer.echo(f"Provider configured: {provider}")
    typer.echo(f"Config: {config_path}")
    if backup_path:
        typer.echo(f"Backup: {backup_path}")


def emit_provider_configure_error(exc: Exception) -> NoReturn:
    """Emit provider configuration errors and exit with CLI validation status."""

    typer.secho(f"Error: {exc}", fg=typer.colors.RED, err=True)
    raise typer.Exit(code=2) from exc
