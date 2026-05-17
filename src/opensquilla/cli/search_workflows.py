"""CLI workflows for search commands."""

from __future__ import annotations

from pathlib import Path

from opensquilla.cli.search_config_mutations import configure_search_provider_in_config
from opensquilla.cli.search_gateway_queries import load_search_status, run_search_query
from opensquilla.cli.search_presenters import (
    emit_search_configure_error,
    emit_search_provider_catalog_payload,
    emit_search_provider_configured,
    emit_search_provider_setup_specs,
    emit_search_query_result,
    emit_search_status,
)
from opensquilla.onboarding.next_steps import env_reference_warnings
from opensquilla.onboarding.search_specs import (
    list_search_provider_setup_specs,
    search_provider_catalog_payload,
)


def list_search_providers_for_cli(*, json_output: bool) -> None:
    """Load and emit the search provider catalog for the CLI."""

    if json_output:
        emit_search_provider_catalog_payload(search_provider_catalog_payload())
        return

    emit_search_provider_setup_specs(list_search_provider_setup_specs())


def show_search_status_for_cli(
    provider: str | None,
    *,
    json_output: bool,
) -> None:
    """Load and emit runtime search diagnostics for the CLI."""

    payload = load_search_status(provider, json_output=json_output)
    emit_search_status(payload, json_output=json_output)


def query_search_for_cli(
    query: str,
    *,
    provider: str | None,
    limit: int | None,
    json_output: bool,
) -> None:
    """Run and emit a diagnostic search query for the CLI."""

    payload = run_search_query(
        query,
        provider=provider,
        limit=limit,
        json_output=json_output,
    )
    emit_search_query_result(query, payload, json_output=json_output)


def configure_search_provider_for_cli(
    provider: str,
    *,
    api_key: str,
    api_key_env: str,
    max_results: int,
    proxy: str,
    use_env_proxy: bool,
    fallback_policy: str,
    diagnostics: bool,
    config_path: Path | None,
) -> None:
    """Configure the active web search provider for the CLI."""

    try:
        result = configure_search_provider_in_config(
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
    except (ValueError, KeyError) as exc:
        emit_search_configure_error(exc)

    emit_search_provider_configured(
        provider,
        config_path=result.persist.path,
        backup_path=result.persist.backup_path,
        warnings=env_reference_warnings(result.config),
    )
