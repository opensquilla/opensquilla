"""Gateway run command — start ASGI gateway with uvicorn."""

from __future__ import annotations

import typer

from opensquilla.cli import gateway_lifecycle_workflows, gateway_run_workflows


def run_gateway(
    port: int = typer.Option(18790, "--port", "-p", help="Port to bind"),
    bind: str = typer.Option("127.0.0.1", "--bind", "-b", help="Host to bind"),
    listen: str = typer.Option("", "--listen", help="Host to bind (wins over --bind)"),
    debug: bool = typer.Option(False, "--debug", help="Enable debug mode"),
) -> None:
    """Start the ASGI gateway server.

    Precedence: ``--listen`` > ``--bind`` > ``OPENSQUILLA_LISTEN`` >
    ``OPENSQUILLA_GATEWAY_HOST`` > default ``127.0.0.1``.
    """
    gateway_run_workflows.run_gateway_for_cli(
        port=port,
        bind=bind,
        listen=listen,
        debug=debug,
    )


def start_gateway(
    port: int = typer.Option(18790, "--port", "-p", help="Port to bind"),
    bind: str = typer.Option("127.0.0.1", "--bind", "-b", help="Host to bind"),
    listen: str = typer.Option("", "--listen", help="Host to bind (wins over --bind)"),
    health_timeout: float = typer.Option(60.0, "--timeout", help="Readiness wait timeout"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Start the gateway in the background and wait for readiness."""

    gateway_lifecycle_workflows.start_gateway_for_cli(
        port=port,
        bind=bind,
        listen=listen,
        health_timeout=health_timeout,
        json_output=json_output,
    )


def status_gateway(
    port: int = typer.Option(18790, "--port", "-p", help="Port to inspect"),
    bind: str = typer.Option("127.0.0.1", "--bind", "-b", help="Host to inspect"),
    listen: str = typer.Option("", "--listen", help="Host to inspect (wins over --bind)"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Inspect the managed gateway process without mutating state."""

    gateway_lifecycle_workflows.status_gateway_for_cli(
        port=port,
        bind=bind,
        listen=listen,
        json_output=json_output,
    )


def stop_gateway(
    port: int = typer.Option(18790, "--port", "-p", help="Port to stop"),
    bind: str = typer.Option("127.0.0.1", "--bind", "-b", help="Host to stop"),
    listen: str = typer.Option("", "--listen", help="Host to stop (wins over --bind)"),
    shutdown_timeout: float = typer.Option(10.0, "--timeout", help="Shutdown wait timeout"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Stop the recorded gateway process."""

    gateway_lifecycle_workflows.stop_gateway_for_cli(
        port=port,
        bind=bind,
        listen=listen,
        shutdown_timeout=shutdown_timeout,
        json_output=json_output,
    )


def restart_gateway(
    port: int = typer.Option(18790, "--port", "-p", help="Port to restart"),
    bind: str = typer.Option("127.0.0.1", "--bind", "-b", help="Host to restart"),
    listen: str = typer.Option("", "--listen", help="Host to restart (wins over --bind)"),
    health_timeout: float = typer.Option(60.0, "--timeout", help="Readiness wait timeout"),
    shutdown_timeout: float = typer.Option(
        10.0, "--shutdown-timeout", help="Shutdown wait timeout"
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Restart the recorded gateway process."""

    gateway_lifecycle_workflows.restart_gateway_for_cli(
        port=port,
        bind=bind,
        listen=listen,
        health_timeout=health_timeout,
        shutdown_timeout=shutdown_timeout,
        json_output=json_output,
    )
