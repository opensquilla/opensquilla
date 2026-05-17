"""Usage/cost CLI commands."""

from __future__ import annotations

import typer

from opensquilla.cli.cost_workflows import show_usage_cost_for_cli

app = typer.Typer(help="Inspect usage and estimated cost.")


@app.callback(invoke_without_command=True)
def cost(
    by_model: bool = typer.Option(False, "--by-model", help="Group aggregate rows by model"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Show aggregate usage/cost from the running gateway."""
    show_usage_cost_for_cli(by_model=by_model, json_output=json_output)
