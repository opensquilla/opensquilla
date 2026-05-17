"""CLI presenters for provider catalog output."""

from __future__ import annotations

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
