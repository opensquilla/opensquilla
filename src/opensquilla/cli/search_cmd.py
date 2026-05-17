"""CLI: opensquilla search list/configure."""

from __future__ import annotations

from pathlib import Path

import typer

from opensquilla.cli.search_workflows import (
    configure_search_provider_for_cli,
    list_search_providers_for_cli,
    query_search_for_cli,
    show_search_status_for_cli,
)

search_app = typer.Typer(help="Configure and inspect web search providers.")


@search_app.command("list")
def search_list(
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """List all known search providers."""
    list_search_providers_for_cli(json_output=json_output)


@search_app.command("status")
def search_status(
    provider: str | None = typer.Argument(None, help="Optional search provider id"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Show runtime search provider diagnostics from the running gateway."""
    show_search_status_for_cli(provider, json_output=json_output)


@search_app.command("query")
def search_query(
    query: str = typer.Argument(..., help="Search query"),
    provider: str | None = typer.Option(None, "--provider", help="Search provider id"),
    limit: int | None = typer.Option(None, "--limit", "-n", help="Maximum results"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Run a diagnostic search query through the running gateway."""
    query_search_for_cli(
        query,
        provider=provider,
        limit=limit,
        json_output=json_output,
    )


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
    configure_search_provider_for_cli(
        provider,
        api_key=api_key,
        api_key_env=api_key_env,
        max_results=max_results,
        proxy=proxy,
        use_env_proxy=use_env_proxy,
        fallback_policy=fallback_policy,
        diagnostics=diagnostics,
        config_path=config_path,
    )
