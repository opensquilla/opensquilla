"""CLI: opensquilla channels list/add/remove/enable/disable."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from opensquilla.cli.channel_fields import (
    apply_channel_token,
    parse_channel_field_pairs,
)
from opensquilla.cli.channels_workflows import (
    describe_channel_type_for_cli,
    list_channel_types_for_cli,
)
from opensquilla.cli.gateway_rpc import confirm_or_exit, run_gateway_sync
from opensquilla.cli.output import print_json
from opensquilla.onboarding.config_store import (
    load_config,
    persist_config,
    resolve_config_path,
)
from opensquilla.onboarding.mutations import (
    list_channel_entries,
    remove_channel,
    set_channel_enabled,
    upsert_channel,
)

channels_app = typer.Typer(help="Manage messaging channels.")


def _print_restart_notice() -> None:
    typer.secho(
        "Restart the gateway PROCESS to apply (this is not the same as "
        "'opensquilla channels restart <name>', which only restarts an "
        "already-loaded adapter).",
        fg=typer.colors.YELLOW,
    )


def _print_channel_verification_next_step(name: str) -> None:
    typer.echo("Next: opensquilla gateway restart")
    typer.echo(f"Verify: uv run opensquilla channels status {name} --json")


_SOURCE_LABEL = {
    "explicit": "from --config",
    "env": "from OPENSQUILLA_GATEWAY_CONFIG_PATH",
    "cwd": "found in cwd",
    "home": "default in $HOME",
}


def _resolve_and_announce(config_path: Path | None) -> Path:
    target, source = resolve_config_path(config_path)
    typer.secho(
        f"Config: {target} ({_SOURCE_LABEL[source]})",
        fg=typer.colors.CYAN,
    )
    return target


def _render_channels_table(entries: list[dict[str, Any]], *, title: str) -> None:
    if not entries:
        typer.echo("0 channels configured.")
        return
    console = Console(width=200, force_terminal=False)
    table = Table(title=title)
    table.add_column("name", no_wrap=True)
    table.add_column("type", no_wrap=True)
    table.add_column("enabled", no_wrap=True)
    table.add_column("agent_id", no_wrap=True)
    table.add_column("details")
    for e in entries:
        details = ", ".join(
            f"{k}={v}"
            for k, v in e.items()
            if k not in {"name", "type", "enabled", "agent_id"}
        )
        table.add_row(
            e["name"],
            e["type"],
            str(e.get("enabled", True)),
            e.get("agent_id", "main"),
            details,
        )
    console.print(table)


def _render_status_table(payload: dict[str, Any], *, name: str | None = None) -> None:
    rows = _filter_status_rows(payload, name)
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


def _filter_status_rows(payload: dict[str, Any], name: str | None) -> list[dict[str, Any]]:
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


@channels_app.command("list")
def channels_list(
    config_path: Path | None = typer.Option(None, "--config"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    target = (
        resolve_config_path(config_path)[0]
        if json_output
        else _resolve_and_announce(config_path)
    )
    cfg = load_config(target)
    entries = list_channel_entries(cfg)
    if json_output:
        print_json(entries)
        return
    _render_channels_table(entries, title=f"Channels in {target}")


@channels_app.command("status")
def channels_status(
    name: str | None = typer.Argument(None, help="Optional channel name to inspect"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Show runtime channel status from the running gateway."""

    async def _run(client):
        return await client.call("channels.status", {})

    payload = run_gateway_sync(_run, json_output=json_output)
    if name:
        filtered = {"channels": _filter_status_rows(payload, name)}
        if json_output:
            print_json(filtered)
            return
        _render_status_table(filtered, name=name)
        return
    if json_output:
        print_json(payload)
        return
    _render_status_table(payload)


@channels_app.command("restart")
def channels_restart(
    name: str = typer.Argument(..., help="Channel name to restart"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Restart a live messaging channel."""

    confirm_or_exit(
        f"Restart channel {name!r}? Message delivery may be interrupted.",
        yes=yes,
        json_output=json_output,
    )

    async def _run(client):
        return await client.call("channels.restart", {"name": name})

    payload = run_gateway_sync(_run, json_output=json_output)
    if json_output:
        print_json(payload)
        return
    typer.echo(f"Channel restarted: {payload.get('channel', name)}")


@channels_app.command("logout")
def channels_logout(
    name: str = typer.Argument(..., help="Channel name to log out"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Log out and disconnect a live messaging channel."""

    confirm_or_exit(
        f"Log out channel {name!r}? Live channel session state will be dropped.",
        yes=yes,
        json_output=json_output,
    )

    async def _run(client):
        return await client.call("channels.logout", {"name": name})

    payload = run_gateway_sync(_run, json_output=json_output)
    if json_output:
        print_json(payload)
        return
    typer.echo(f"Channel logged out: {payload.get('channel', name)}")


@channels_app.command("add")
def channels_add(
    type_name: str = typer.Argument(..., help="Channel type (e.g. slack)."),
    name: str = typer.Option(..., "--name"),
    token: str = typer.Option("", "--token"),
    enabled: bool = typer.Option(True, "--enabled/--disabled"),
    agent_id: str = typer.Option("main", "--agent-id"),
    fields: list[str] = typer.Option(
        [], "--field", "-f", help="Repeatable key=value channel field."
    ),
    config_path: Path | None = typer.Option(None, "--config"),
) -> None:
    """Add or update a channel entry."""
    target = _resolve_and_announce(config_path)
    payload: dict[str, Any] = {
        "type": type_name,
        "name": name,
        "enabled": enabled,
        "agent_id": agent_id,
    }
    apply_channel_token(payload, type_name, token)
    payload.update(parse_channel_field_pairs(fields, type_name))

    cfg = load_config(target)
    try:
        result = upsert_channel(cfg, entry_payload=payload)
    except (ValueError, KeyError) as exc:
        typer.secho(f"Error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc

    persist = persist_config(result.config, path=target, restart_required=True)
    typer.echo(f"Channel saved: {name} ({type_name})")
    if persist.backup_path:
        typer.echo(f"Backup: {persist.backup_path}")
    _print_restart_notice()
    _print_channel_verification_next_step(name)


@channels_app.command("remove")
def channels_remove(
    name: str = typer.Argument(...),
    config_path: Path | None = typer.Option(None, "--config"),
) -> None:
    target = _resolve_and_announce(config_path)
    cfg = load_config(target)
    try:
        result = remove_channel(cfg, name=name)
    except KeyError as exc:
        typer.secho(f"Error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc
    persist_config(result.config, path=target, restart_required=True)
    typer.echo(f"Channel removed: {name}")
    _print_restart_notice()


@channels_app.command("enable")
def channels_enable(
    name: str = typer.Argument(...),
    config_path: Path | None = typer.Option(None, "--config"),
) -> None:
    target = _resolve_and_announce(config_path)
    cfg = load_config(target)
    try:
        result = set_channel_enabled(cfg, name=name, enabled=True)
    except KeyError as exc:
        typer.secho(f"Error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc
    persist_config(result.config, path=target, restart_required=True)
    typer.echo(f"Channel enabled: {name}")
    _print_restart_notice()


@channels_app.command("disable")
def channels_disable(
    name: str = typer.Argument(...),
    config_path: Path | None = typer.Option(None, "--config"),
) -> None:
    target = _resolve_and_announce(config_path)
    cfg = load_config(target)
    try:
        result = set_channel_enabled(cfg, name=name, enabled=False)
    except KeyError as exc:
        typer.secho(f"Error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc
    persist_config(result.config, path=target, restart_required=True)
    typer.echo(f"Channel disabled: {name}")
    _print_restart_notice()


@channels_app.command("edit")
def channels_edit(
    name: str = typer.Argument(..., help="Existing channel name."),
    token: str = typer.Option("", "--token"),
    enabled: bool | None = typer.Option(None, "--enabled/--disabled"),
    agent_id: str = typer.Option("", "--agent-id"),
    fields: list[str] = typer.Option(
        [], "--field", "-f", help="Repeatable key=value channel field."
    ),
    config_path: Path | None = typer.Option(None, "--config"),
) -> None:
    """Edit an existing channel; blank fields keep current values."""
    target = _resolve_and_announce(config_path)
    cfg = load_config(target)
    existing = next(
        (
            e.model_dump(mode="python")
            for e in cfg.channels.channels
            if e.name == name
        ),
        None,
    )
    if existing is None:
        typer.secho(f"Error: no channel named {name!r}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)
    type_name = existing["type"]

    overrides: dict[str, Any] = {"type": type_name, "name": name}
    if enabled is not None:
        overrides["enabled"] = enabled
    if agent_id:
        overrides["agent_id"] = agent_id
    apply_channel_token(overrides, type_name, token)
    overrides.update(parse_channel_field_pairs(fields, type_name))
    # Patch semantics: every field not explicitly overridden retains its
    # existing value. upsert_channel's secret-merge guards against blanks
    # in the add path; this seeding handles non-secret partial updates
    # in the edit path.
    payload = {**existing, **overrides}

    try:
        result = upsert_channel(cfg, entry_payload=payload)
    except (ValueError, KeyError) as exc:
        typer.secho(f"Error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc

    persist = persist_config(result.config, path=target, restart_required=True)
    typer.echo(f"Channel updated: {name} ({type_name})")
    if persist.backup_path:
        typer.echo(f"Backup: {persist.backup_path}")
    _print_restart_notice()
    _print_channel_verification_next_step(name)


@channels_app.command("types")
def channels_types(
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """List supported channel types."""
    list_channel_types_for_cli(json_output=json_output)


@channels_app.command("describe")
def channels_describe(
    type_name: str = typer.Argument(..., help="Channel type, e.g. slack."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Show the field schema, transport, and docs hint for a channel type."""
    describe_channel_type_for_cli(type_name, json_output=json_output)
