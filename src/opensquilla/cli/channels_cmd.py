"""CLI: opensquilla channels list/add/remove/enable/disable."""

from __future__ import annotations

from pathlib import Path

import typer

from opensquilla.cli.channels_workflows import (
    add_channel_for_cli,
    describe_channel_type_for_cli,
    edit_channel_for_cli,
    list_channel_types_for_cli,
    list_configured_channels_for_cli,
    logout_channel_for_cli,
    restart_channel_for_cli,
    show_channel_status_for_cli,
)
from opensquilla.onboarding.config_store import (
    load_config,
    persist_config,
    resolve_config_path,
)
from opensquilla.onboarding.mutations import (
    remove_channel,
    set_channel_enabled,
)

channels_app = typer.Typer(help="Manage messaging channels.")


def _print_restart_notice() -> None:
    typer.secho(
        "Restart the gateway PROCESS to apply (this is not the same as "
        "'opensquilla channels restart <name>', which only restarts an "
        "already-loaded adapter).",
        fg=typer.colors.YELLOW,
    )


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


@channels_app.command("list")
def channels_list(
    config_path: Path | None = typer.Option(None, "--config"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    list_configured_channels_for_cli(config_path, json_output=json_output)


@channels_app.command("status")
def channels_status(
    name: str | None = typer.Argument(None, help="Optional channel name to inspect"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Show runtime channel status from the running gateway."""
    show_channel_status_for_cli(name, json_output=json_output)


@channels_app.command("restart")
def channels_restart(
    name: str = typer.Argument(..., help="Channel name to restart"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Restart a live messaging channel."""
    restart_channel_for_cli(name, yes=yes, json_output=json_output)


@channels_app.command("logout")
def channels_logout(
    name: str = typer.Argument(..., help="Channel name to log out"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Log out and disconnect a live messaging channel."""
    logout_channel_for_cli(name, yes=yes, json_output=json_output)


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
    add_channel_for_cli(
        type_name,
        name=name,
        token=token,
        enabled=enabled,
        agent_id=agent_id,
        fields=fields,
        config_path=config_path,
    )


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
    edit_channel_for_cli(
        name,
        token=token,
        enabled=enabled,
        agent_id=agent_id,
        fields=fields,
        config_path=config_path,
    )


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
