"""CLI workflows for provider commands."""

from __future__ import annotations

from opensquilla.cli.providers_gateway_queries import load_provider_status
from opensquilla.cli.providers_presenters import (
    emit_provider_catalog_payload,
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
