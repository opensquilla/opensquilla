"""CLI: opensquilla providers list/configure."""

from __future__ import annotations

from pathlib import Path

import typer

from opensquilla.cli.providers_workflows import (
    list_providers_for_cli,
    show_provider_status_for_cli,
)
from opensquilla.onboarding.config_store import (
    default_config_path,
    load_config,
    persist_config,
)
from opensquilla.onboarding.mutations import upsert_llm_provider

providers_app = typer.Typer(help="Configure and inspect LLM providers.")


@providers_app.command("list")
def providers_list(
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """List all known providers (supported and disabled)."""
    list_providers_for_cli(json_output=json_output)


@providers_app.command("status")
def providers_status(
    provider: str | None = typer.Argument(None, help="Optional provider id"),
    probe_models: bool = typer.Option(
        False,
        "--probe-models",
        help="Probe model listing for the active provider",
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Show runtime provider diagnostics from the running gateway."""
    show_provider_status_for_cli(
        provider,
        probe_models=probe_models,
        json_output=json_output,
    )


@providers_app.command("configure")
def providers_configure(
    provider: str = typer.Argument(..., help="Provider id (e.g. openrouter)."),
    model: str = typer.Option("", "--model", "-m"),
    api_key: str = typer.Option("", "--api-key", "-k"),
    base_url: str = typer.Option("", "--base-url"),
    proxy: str = typer.Option("", "--proxy"),
    config_path: Path | None = typer.Option(
        None, "--config", help="Override config path."
    ),
) -> None:
    """Configure the active LLM provider."""
    target = config_path or default_config_path()
    cfg = load_config(target)
    try:
        result = upsert_llm_provider(
            cfg,
            provider_id=provider,
            model=model,
            api_key=api_key,
            base_url=base_url,
            proxy=proxy,
        )
    except (ValueError, KeyError) as exc:
        typer.secho(f"Error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc

    persist = persist_config(
        result.config, path=target, restart_required=result.restart_required
    )
    typer.echo(f"Provider configured: {provider}")
    typer.echo(f"Config: {persist.path}")
    if persist.backup_path:
        typer.echo(f"Backup: {persist.backup_path}")
