"""CLI presenters for channel catalog output."""

from __future__ import annotations

from typing import NoReturn

import typer
from rich.console import Console
from rich.table import Table

from opensquilla.cli.output import print_json
from opensquilla.onboarding.channel_specs import ChannelSetupSpec


def emit_channel_types(
    specs: list[ChannelSetupSpec],
    *,
    json_output: bool,
) -> None:
    """Emit supported channel types."""

    if json_output:
        print_json([
            {
                "type": spec.type,
                "label": spec.label,
                "transport": spec.transport,
                "requires_public_url": spec.requires_public_url,
                "dependency_extra": spec.dependency_extra,
            }
            for spec in specs
        ])
        return

    table = Table(title="Supported channel types")
    table.add_column("type", no_wrap=True)
    table.add_column("label")
    table.add_column("transport", no_wrap=True)
    table.add_column("public URL", no_wrap=True)
    table.add_column("extras", no_wrap=True)
    for spec in specs:
        table.add_row(
            spec.type,
            spec.label,
            spec.transport,
            "yes" if spec.requires_public_url else "no",
            spec.dependency_extra or "—",
        )
    Console(width=140, force_terminal=False).print(table)


def emit_channel_type_description(
    spec: ChannelSetupSpec,
    *,
    json_output: bool,
) -> None:
    """Emit details for one channel type."""

    if json_output:
        print_json({
            "type": spec.type,
            "label": spec.label,
            "description": spec.description,
            "transport": spec.transport,
            "requires_public_url": spec.requires_public_url,
            "dependency_extra": spec.dependency_extra,
            "restart_required": spec.restart_required,
            "docs_hint": spec.docs_hint,
            "fields": [
                {
                    "name": field.name,
                    "label": field.label,
                    "type": field.field_type,
                    "required": field.required,
                    "default": field.default,
                    "choices": list(field.choices),
                    "secret": field.secret,
                    "description": field.description,
                }
                for field in spec.fields
            ],
        })
        return

    console = Console(width=160, force_terminal=False)
    typer.echo(f"{spec.label} ({spec.type})")
    typer.echo(spec.description)
    typer.echo(
        f"transport={spec.transport}  "
        f"public_url={'yes' if spec.requires_public_url else 'no'}  "
        f"extras={spec.dependency_extra or '—'}  "
        f"docs={spec.docs_hint}"
    )
    table = Table(title="Fields")
    table.add_column("name", no_wrap=True)
    table.add_column("type", no_wrap=True)
    table.add_column("required", no_wrap=True)
    table.add_column("secret", no_wrap=True)
    table.add_column("default")
    table.add_column("choices")
    for field in spec.fields:
        table.add_row(
            field.name,
            field.field_type,
            "yes" if field.required else "no",
            "yes" if field.secret else "no",
            "" if field.default is None else str(field.default),
            ",".join(field.choices) if field.choices else "—",
        )
    console.print(table)


def emit_channel_catalog_error(exc: Exception) -> NoReturn:
    """Emit channel catalog lookup errors and exit with validation status."""

    typer.secho(f"Error: {exc}", fg=typer.colors.RED, err=True)
    raise typer.Exit(code=2) from exc
