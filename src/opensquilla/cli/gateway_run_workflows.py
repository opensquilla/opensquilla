"""Workflow helpers for ``opensquilla gateway run``."""

from __future__ import annotations

import asyncio
import os

from opensquilla.cli import gateway_run_presenters
from opensquilla.gateway.boot import start_gateway_server
from opensquilla.gateway.config import GatewayConfig, resolve_listen_address
from opensquilla.gateway.websocket import SubscriptionManager


def build_gateway_run_config(
    *,
    port: int,
    bind: str,
    listen: str,
    debug: bool,
) -> GatewayConfig:
    """Resolve listen settings and load the gateway run config."""

    # Treat the CLI ``--bind`` default as "not explicitly supplied" so the
    # env vars get a chance to participate when the operator only sets env.
    explicit_flag: str | None = listen or (bind if bind != "127.0.0.1" else None)
    host = resolve_listen_address(explicit_flag)
    config = GatewayConfig.load(os.environ.get("OPENSQUILLA_GATEWAY_CONFIG_PATH"))
    return config.model_copy(update={"host": host, "port": port, "debug": debug})


async def run_gateway_server(config: GatewayConfig) -> None:
    """Create gateway-scoped services and wait for the ASGI server task."""

    # Subscription manager is gateway-specific (WS event routing).
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


def run_gateway_for_cli(
    *,
    port: int,
    bind: str,
    listen: str,
    debug: bool,
) -> None:
    """Run the gateway from the Typer command boundary."""

    config = build_gateway_run_config(port=port, bind=bind, listen=listen, debug=debug)
    gateway_run_presenters.render_gateway_startup(host=config.host, port=config.port, config=config)
    try:
        asyncio.run(run_gateway_server(config))
    except KeyboardInterrupt:
        gateway_run_presenters.render_gateway_stopped()
