"""CLI presenters for gateway lifecycle command output."""

from __future__ import annotations

import typer

from opensquilla.cli.gateway_lifecycle import GatewayLifecycleResult
from opensquilla.cli.output import print_json


def emit_lifecycle_result(result: GatewayLifecycleResult, *, json_output: bool) -> None:
    """Emit a managed gateway lifecycle result using the existing CLI contract."""

    if json_output:
        print_json(result.to_payload())
    elif result.ok:
        typer.echo(f"{result.state}: {result.url}")
    else:
        typer.echo(f"Error: {result.message or result.code or result.state}", err=True)

    if result.exit_code != 0:
        raise typer.Exit(code=result.exit_code)
