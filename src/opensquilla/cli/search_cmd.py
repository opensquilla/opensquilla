"""CLI: opensquilla search list/configure."""

from __future__ import annotations

import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from opensquilla.cli.gateway_rpc import run_gateway_sync
from opensquilla.cli.output import print_json
from opensquilla.cli.ui import warning_panel
from opensquilla.onboarding.config_store import (
    default_config_path,
    load_config,
    persist_config,
)
from opensquilla.onboarding.mutations import upsert_search_provider
from opensquilla.onboarding.next_steps import env_reference_warnings
from opensquilla.onboarding.search_specs import (
    list_search_provider_setup_specs,
    search_provider_catalog_payload,
)

search_app = typer.Typer(help="Configure and inspect web search providers.")


@search_app.command("list")
def search_list(
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """List all known search providers."""
    if json_output:
        print_json(search_provider_catalog_payload())
        return

    console = Console(width=160, force_terminal=False)
    table = Table(title="Search providers")
    table.add_column("provider", no_wrap=True)
    table.add_column("label", no_wrap=True)
    table.add_column("runtime", no_wrap=True)
    table.add_column("requires key", no_wrap=True)
    table.add_column("env key")
    for spec in list_search_provider_setup_specs():
        table.add_row(
            spec.provider_id,
            spec.label,
            "supported" if spec.runtime_supported else "unsupported (disabled)",
            "yes" if spec.requires_api_key else "no",
            spec.env_key or "-",
        )
    console.print(table)


@search_app.command("status")
def search_status(
    provider: str | None = typer.Argument(None, help="Optional search provider id"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
    config_path: Path | None = typer.Option(None, "--config", help="Override config path."),
) -> None:
    """Show runtime search provider diagnostics from the running gateway."""

    async def _run(client):
        params: dict[str, object] = {}
        if provider:
            params["provider"] = provider
        return await client.call("search.status", params)

    payload = run_gateway_sync(_run, json_output=json_output, config_path=config_path)
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


@search_app.command("query")
def search_query(
    query: str = typer.Argument(..., help="Search query"),
    provider: str | None = typer.Option(None, "--provider", help="Search provider id"),
    limit: int | None = typer.Option(None, "--limit", "-n", help="Maximum results"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Run a diagnostic search query through the running gateway."""

    async def _run(client):
        params: dict[str, object] = {"query": query}
        if provider:
            params["provider"] = provider
        if limit is not None:
            params["limit"] = limit
        return await client.call("search.query", params)

    payload = run_gateway_sync(_run, json_output=json_output)
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


@search_app.command("configure")
def search_configure(
    provider: str = typer.Argument(..., help="Search provider id (e.g. brave)."),
    api_key: str = typer.Option("", "--api-key", "-k"),
    api_key_env: str = typer.Option("", "--api-key-env"),
    max_results: int = typer.Option(5, "--max-results"),
    proxy: str = typer.Option("", "--proxy"),
    use_env_proxy: bool = typer.Option(
        False, "--use-env-proxy/--no-use-env-proxy"
    ),
    fallback_policy: str = typer.Option("off", "--fallback-policy"),
    diagnostics: bool = typer.Option(False, "--diagnostics/--no-diagnostics"),
    config_path: Path | None = typer.Option(
        None, "--config", help="Override config path."
    ),
) -> None:
    """Configure the active web search provider."""
    target = config_path or default_config_path()
    cfg = load_config(target)
    try:
        result = upsert_search_provider(
            cfg,
            provider_id=provider,
            api_key=api_key,
            api_key_env=api_key_env,
            max_results=max_results,
            proxy=proxy,
            use_env_proxy=use_env_proxy,
            fallback_policy=fallback_policy,
            diagnostics=diagnostics,
        )
    except (ValueError, KeyError) as exc:
        typer.secho(f"Error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc

    persist = persist_config(
        result.config, path=target, restart_required=result.restart_required
    )
    typer.echo(f"Search provider configured: {provider}")
    typer.echo(f"Config: {persist.path}")
    warning_console = Console(file=sys.stdout, width=160, force_terminal=False)
    for warning in env_reference_warnings(result.config):
        warning_console.print(warning_panel(warning))
    if persist.backup_path:
        typer.echo(f"Backup: {persist.backup_path}")
