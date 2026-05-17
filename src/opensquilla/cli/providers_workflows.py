"""CLI workflows for provider commands."""

from __future__ import annotations

from pathlib import Path

from opensquilla.cli.providers_config_mutations import configure_provider_in_config
from opensquilla.cli.providers_gateway_queries import load_provider_status
from opensquilla.cli.providers_presenters import (
    emit_provider_catalog_payload,
    emit_provider_configure_error,
    emit_provider_configured,
    emit_provider_setup_specs,
    emit_provider_status,
)
from opensquilla.onboarding.provider_specs import (
    list_provider_setup_specs,
    provider_catalog_payload,
)


def list_providers_for_cli(*, json_output: bool) -> None:
    """Load and emit the provider catalog for the CLI."""

    if json_output:
        emit_provider_catalog_payload(provider_catalog_payload())
        return

    emit_provider_setup_specs(list_provider_setup_specs())


def show_provider_status_for_cli(
    provider: str | None,
    *,
    probe_models: bool,
    json_output: bool,
) -> None:
    """Load and emit runtime provider diagnostics for the CLI."""

    payload = load_provider_status(
        provider,
        probe_models=probe_models,
        json_output=json_output,
    )
    emit_provider_status(payload, json_output=json_output)


def configure_provider_for_cli(
    provider: str,
    *,
    model: str,
    api_key: str,
    base_url: str,
    proxy: str,
    config_path: Path | None,
) -> None:
    """Configure the active LLM provider for the CLI."""

    try:
        persist = configure_provider_in_config(
            provider,
            model=model,
            api_key=api_key,
            base_url=base_url,
            proxy=proxy,
            config_path=config_path,
        )
    except (ValueError, KeyError) as exc:
        emit_provider_configure_error(exc)

    emit_provider_configured(
        provider,
        config_path=persist.path,
        backup_path=persist.backup_path,
    )
