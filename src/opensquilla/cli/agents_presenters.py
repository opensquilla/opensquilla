"""CLI presenters for durable agent commands."""

from __future__ import annotations

from pathlib import Path
from typing import Any, NoReturn

import typer
from rich.console import Console
from rich.table import Table

from opensquilla.cli.output import print_json
from opensquilla.onboarding.config_store import PersistResult


def emit_agents(
    agents: list[dict[str, Any]],
    *,
    config_path: Path,
    json_output: bool,
) -> None:
    """Emit configured agents."""

    if json_output:
        print_json(agents)
        return

    console = Console(width=200, force_terminal=False)
    table = Table(title=f"Agents in {config_path}")
    table.add_column("id", no_wrap=True)
    table.add_column("name", no_wrap=True)
    table.add_column("type", no_wrap=True)
    table.add_column("enabled", no_wrap=True)
    table.add_column("model", no_wrap=True)
    table.add_column("workspace")
    for agent in agents:
        table.add_row(
            str(agent.get("id", "")),
            str(agent.get("name", "")),
            str(agent.get("type", "")),
            str(agent.get("enabled", True)),
            str(agent.get("model") or ""),
            str(agent.get("workspace") or ""),
        )
    console.print(table)


def emit_agent_saved(
    agent: dict[str, Any],
    *,
    persist: PersistResult,
    json_output: bool,
) -> None:
    """Emit successful agent creation output."""

    if json_output:
        print_json(agent)
        return

    typer.echo(f"Agent saved: {agent['id']}")
    typer.echo(f"Config: {persist.path}")
    if persist.backup_path:
        typer.echo(f"Backup: {persist.backup_path}")
    emit_agent_restart_notice()


def emit_agent_deleted(
    payload: dict[str, Any],
    *,
    agent_id: str,
    persist: PersistResult,
    json_output: bool,
) -> None:
    """Emit successful agent deletion output."""

    if json_output:
        print_json(payload)
        return

    typer.echo(f"Agent deleted: {agent_id}")
    typer.echo(f"Config: {persist.path}")
    typer.echo("Workspace and state were left untouched.")
    emit_agent_restart_notice()


def confirm_agent_delete(agent_id: str, *, force: bool) -> None:
    """Confirm destructive agent config mutation when not forced."""

    if not force:
        typer.confirm(f"Delete agent {agent_id!r} from config?", abort=True)


def emit_agent_restart_notice() -> None:
    """Emit the config-change gateway restart notice."""

    typer.secho(
        "Agent changes require restarting the gateway to take effect.",
        fg=typer.colors.YELLOW,
    )


def emit_agent_config_error(exc: Exception) -> NoReturn:
    """Emit agent configuration errors and exit with CLI validation status."""

    typer.secho(f"Error: {exc}", fg=typer.colors.RED, err=True)
    raise typer.Exit(code=2) from exc
