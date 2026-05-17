"""Config command — get/set configuration values."""

from __future__ import annotations

from pathlib import Path

import typer

from opensquilla.cli.config_workflows import get_config_for_cli, set_config_for_cli

app = typer.Typer(help="Manage OpenSquilla configuration.")


@app.command("get")
def config_get(
    key: str = typer.Argument("", help="Config key to get (empty = show all)"),
    config_path: Path | None = typer.Option(None, "--config", help="Override config path."),
) -> None:
    """Get a configuration value."""
    get_config_for_cli(key, config_path=config_path)


@app.command("set")
def config_set(
    key: str = typer.Argument(..., help="Config key (dot-notation)"),
    value: str = typer.Argument(..., help="Value to set"),
) -> None:
    """Set a configuration value (env-var backed, prints export command)."""
    set_config_for_cli(key, value)
