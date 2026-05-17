"""CLI presenters for channel output."""

from __future__ import annotations

from typing import Any, NoReturn

import typer
from rich.console import Console
from rich.table import Table

from opensquilla.cli.output import print_json
from opensquilla.onboarding.channel_specs import ChannelSetupSpec

_SOURCE_LABEL = {
    "explicit": "from --config",
    "env": "from OPENSQUILLA_GATEWAY_CONFIG_PATH",
    "cwd": "found in cwd",
    "home": "default in $HOME",
}


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


def emit_channel_config_error(exc: Exception) -> NoReturn:
    """Emit channel configuration errors and exit with validation status."""

    typer.secho(f"Error: {exc}", fg=typer.colors.RED, err=True)
    raise typer.Exit(code=2) from exc


def emit_channel_config_path(config_path: object, *, source: str) -> None:
    """Emit the resolved channel config path."""

    typer.secho(
        f"Config: {config_path} ({_SOURCE_LABEL[source]})",
        fg=typer.colors.CYAN,
    )


def emit_configured_channels(
    entries: list[dict[str, Any]],
    *,
    config_path: object,
    json_output: bool,
) -> None:
    """Emit configured channel entries."""

    if json_output:
        print_json(entries)
        return

    if not entries:
        typer.echo("0 channels configured.")
        return

    console = Console(width=200, force_terminal=False)
    table = Table(title=f"Channels in {config_path}")
    table.add_column("name", no_wrap=True)
    table.add_column("type", no_wrap=True)
    table.add_column("enabled", no_wrap=True)
    table.add_column("agent_id", no_wrap=True)
    table.add_column("details")
    for entry in entries:
        details = ", ".join(
            f"{key}={value}"
            for key, value in entry.items()
            if key not in {"name", "type", "enabled", "agent_id"}
        )
        table.add_row(
            entry["name"],
            entry["type"],
            str(entry.get("enabled", True)),
            entry.get("agent_id", "main"),
            details,
        )
    console.print(table)


def emit_channel_saved(
    name: str,
    type_name: str,
    *,
    backup_path: object | None,
) -> None:
    """Emit successful channel save output."""

    typer.echo(f"Channel saved: {name} ({type_name})")
    if backup_path:
        typer.echo(f"Backup: {backup_path}")


def emit_channel_updated(
    name: str,
    type_name: str,
    *,
    backup_path: object | None,
) -> None:
    """Emit successful channel update output."""

    typer.echo(f"Channel updated: {name} ({type_name})")
    if backup_path:
        typer.echo(f"Backup: {backup_path}")


def emit_channel_restart_notice() -> None:
    """Emit the config-change gateway restart notice."""

    typer.secho(
        "Restart the gateway PROCESS to apply (this is not the same as "
        "'opensquilla channels restart <name>', which only restarts an "
        "already-loaded adapter).",
        fg=typer.colors.YELLOW,
    )


def emit_channel_verification_next_step(name: str) -> None:
    """Emit the next verification step after a channel config mutation."""

    typer.echo("Next: opensquilla gateway restart")
    typer.echo(f"Verify: uv run opensquilla channels status {name} --json")


def emit_channel_status(
    payload: dict[str, Any],
    *,
    name: str | None,
    json_output: bool,
) -> None:
    """Emit runtime channel status."""

    if name:
        payload = {"channels": _filter_channel_status_rows(payload, name)}

    if json_output:
        print_json(payload)
        return

    _emit_channel_status_table(payload)


def emit_channel_action_result(
    payload: dict[str, Any],
    *,
    action_label: str,
    fallback_channel: str,
    json_output: bool,
) -> None:
    """Emit the result of a live channel action."""

    if json_output:
        print_json(payload)
        return

    typer.echo(f"Channel {action_label}: {payload.get('channel', fallback_channel)}")


def _emit_channel_status_table(payload: dict[str, Any]) -> None:
    rows = _filter_channel_status_rows(payload, None)
    table = Table(title="Channel status", show_header=True, header_style="bold cyan")
    table.add_column("Name")
    table.add_column("Type")
    table.add_column("Status")
    table.add_column("Connected")
    table.add_column("Enabled")
    table.add_column("Configured")
    table.add_column("Restart attempts", justify="right")
    for row in rows:
        table.add_row(
            str(row.get("name") or ""),
            str(row.get("type") or ""),
            str(row.get("status") or ""),
            str(row.get("connected") or False),
            str(row.get("enabled") or False),
            str(row.get("configured") or False),
            str(row.get("restart_attempts") or 0),
        )
    Console(width=180, force_terminal=False).print(table)


def _filter_channel_status_rows(
    payload: dict[str, Any],
    name: str | None,
) -> list[dict[str, Any]]:
    rows = payload.get("channels", []) if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        return []
    if not name:
        return [row for row in rows if isinstance(row, dict)]
    return [
        row
        for row in rows
        if isinstance(row, dict) and str(row.get("name") or "") == name
    ]
