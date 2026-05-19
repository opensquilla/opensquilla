"""Gateway run command — start ASGI gateway with uvicorn."""

from __future__ import annotations

import asyncio
import os

import typer

from opensquilla.cli import gateway_lifecycle_workflows
from opensquilla.cli.ui import console
from opensquilla.gateway.boot import start_gateway_server
from opensquilla.gateway.config import GatewayConfig, is_public_bind, resolve_listen_address
from opensquilla.paths import default_opensquilla_home


def gateway_startup_guidance(host: str, port: int) -> tuple[str, ...]:
    """Return operator-facing guidance shown after the gateway starts."""

    base_url = f"http://{host}:{port}"
    return (
        f"[bold]Web UI:[/bold] {base_url}/control/",
        f"[bold]API base:[/bold] {base_url}",
        f"[bold]Debug log:[/bold] {default_opensquilla_home() / 'logs' / 'debug.log'}",
        "[dim]Keep this terminal open. Press Ctrl+C to stop.[/dim]",
    )


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
    # Treat the CLI ``--bind`` default as "not explicitly supplied" so the
    # env vars get a chance to participate when the operator only sets env.
    explicit_flag: str | None = listen or (bind if bind != "127.0.0.1" else None)
    host = resolve_listen_address(explicit_flag)
    config = GatewayConfig.load(os.environ.get("OPENSQUILLA_GATEWAY_CONFIG_PATH"))
    config = config.model_copy(update={"host": host, "port": port, "debug": debug})

    banner_host = f"[red]{host}[/red]" if is_public_bind(host) else f"[cyan]{host}[/cyan]"
    console.print(f"[bold green]Starting OpenSquilla gateway[/bold green] on {banner_host}:{port}")
    for line in gateway_startup_guidance(host, port):
        console.print(line)
    if is_public_bind(host):
        # Use ASCII-only glyphs here so the warning still prints on Windows
        # consoles configured for legacy GBK code pages (where U+26A0 / em-dash
        # crash Rich's legacy renderer with UnicodeEncodeError).
        console.print(
            "[yellow]WARNING: gateway is bound to a wildcard address - "
            "reachable from every interface.[/yellow]"
        )
        if config.auth.mode == "none":
            console.print(
                "[yellow]  auth.mode=none + wildcard bind = LAN-open. "
                "Anyone reachable on this network can use the chat, sessions, "
                "and config surfaces with your provider credentials.[/yellow]"
            )
        console.print(
            "[yellow]  Bypass / elevated mode remains owner-only and "
            "is unreachable from non-loopback peers; the chat UI will "
            "self-disable that pill.[/yellow]"
        )

    async def _run() -> None:
        # Subscription manager is gateway-specific (WS event routing)
        from opensquilla.gateway.websocket import SubscriptionManager

        subscription_mgr = SubscriptionManager()

        # build_services() inside start_gateway_server handles:
        # session_manager, provider_selector, tool_registry, usage_tracker,
        # memory, skills, scheduler, search, MCP discovery.
        server = await start_gateway_server(
            config=config,
            subscription_manager=subscription_mgr,
            run=True,
        )
        assert server._task is not None
        try:
            await server._task
        except (KeyboardInterrupt, asyncio.CancelledError):
            await server.close("keyboard_interrupt")

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        console.print("\n[yellow]Gateway stopped.[/yellow]")


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
