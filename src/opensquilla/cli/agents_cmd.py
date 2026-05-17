"""CLI: opensquilla agents list/add/delete."""

from __future__ import annotations

from pathlib import Path

import typer

from opensquilla.cli.agents_workflows import (
    add_agent_for_cli,
    delete_agent_for_cli,
    list_agents_for_cli,
)

agents_app = typer.Typer(help="Manage durable agents.")


@agents_app.command("list")
def agents_list(
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
    config_path: Path | None = typer.Option(None, "--config"),
) -> None:
    """List configured agents."""
    list_agents_for_cli(config_path, json_output=json_output)


@agents_app.command("add")
def agents_add(
    agent_id: str = typer.Argument(..., help="Agent id to add."),
    model: str | None = typer.Option(None, "--model", help="Default model for this agent."),
    workspace: Path | None = typer.Option(None, "--workspace", help="Workspace directory."),
    name: str | None = typer.Option(None, "--name", help="Display name."),
    description: str | None = typer.Option(None, "--description", help="Agent description."),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
    config_path: Path | None = typer.Option(None, "--config"),
) -> None:
    """Add a durable agent entry to config."""
    add_agent_for_cli(
        agent_id,
        model=model,
        workspace=workspace,
        name=name,
        description=description,
        json_output=json_output,
        config_path=config_path,
    )


@agents_app.command("delete")
def agents_delete(
    agent_id: str = typer.Argument(..., help="Agent id to delete."),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation."),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
    config_path: Path | None = typer.Option(None, "--config"),
) -> None:
    """Delete a durable agent entry from config."""
    delete_agent_for_cli(
        agent_id,
        force=force,
        json_output=json_output,
        config_path=config_path,
    )
