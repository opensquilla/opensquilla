"""CLI workflows for provider commands."""

from __future__ import annotations

from opensquilla.cli.providers_presenters import (
    emit_provider_catalog_payload,
    emit_provider_setup_specs,
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
