"""CLI workflows for gateway lifecycle commands."""

from __future__ import annotations

import os
from typing import Literal

from opensquilla.cli.gateway_lifecycle import GatewayLifecycleManager, GatewayLifecycleResult
from opensquilla.cli.gateway_lifecycle_presenters import emit_lifecycle_result
from opensquilla.gateway.config import resolve_listen_address

LifecycleAction = Literal["start", "status", "stop", "restart"]


def resolve_lifecycle_host(*, bind: str, listen: str) -> str:
    """Resolve the managed gateway host using the gateway CLI precedence rules."""

    explicit_flag: str | None = listen or (bind if bind != "127.0.0.1" else None)
    return resolve_listen_address(explicit_flag)


def build_lifecycle_manager(
    *,
    port: int,
    bind: str,
    listen: str,
    health_timeout: float = 60.0,
    shutdown_timeout: float = 10.0,
) -> GatewayLifecycleManager:
    """Build the managed gateway lifecycle coordinator for CLI commands."""

    return GatewayLifecycleManager(
        host=resolve_lifecycle_host(bind=bind, listen=listen),
        port=port,
        config_path=os.environ.get("OPENSQUILLA_GATEWAY_CONFIG_PATH") or None,
        health_timeout=health_timeout,
        shutdown_timeout=shutdown_timeout,
    )


def run_lifecycle_action_for_cli(
    action: LifecycleAction,
    *,
    port: int,
    bind: str,
    listen: str,
    health_timeout: float = 60.0,
    shutdown_timeout: float = 10.0,
    json_output: bool,
) -> None:
    """Run a lifecycle action and emit the CLI result."""

    result = run_lifecycle_action(
        action,
        port=port,
        bind=bind,
        listen=listen,
        health_timeout=health_timeout,
        shutdown_timeout=shutdown_timeout,
    )
    emit_lifecycle_result(result, json_output=json_output)


def run_lifecycle_action(
    action: LifecycleAction,
    *,
    port: int,
    bind: str,
    listen: str,
    health_timeout: float = 60.0,
    shutdown_timeout: float = 10.0,
) -> GatewayLifecycleResult:
    """Run a lifecycle action and return its result for presentation."""

    manager = build_lifecycle_manager(
        port=port,
        bind=bind,
        listen=listen,
        health_timeout=health_timeout,
        shutdown_timeout=shutdown_timeout,
    )
    if action == "start":
        return manager.start()
    if action == "status":
        return manager.status()
    if action == "stop":
        return manager.stop()
    return manager.restart()


def start_gateway_for_cli(
    *,
    port: int,
    bind: str,
    listen: str,
    health_timeout: float,
    json_output: bool,
) -> None:
    """Start the managed gateway and emit the CLI result."""

    run_lifecycle_action_for_cli(
        "start",
        port=port,
        bind=bind,
        listen=listen,
        health_timeout=health_timeout,
        json_output=json_output,
    )


def status_gateway_for_cli(
    *,
    port: int,
    bind: str,
    listen: str,
    json_output: bool,
) -> None:
    """Inspect the managed gateway and emit the CLI result."""

    run_lifecycle_action_for_cli(
        "status",
        port=port,
        bind=bind,
        listen=listen,
        json_output=json_output,
    )


def stop_gateway_for_cli(
    *,
    port: int,
    bind: str,
    listen: str,
    shutdown_timeout: float,
    json_output: bool,
) -> None:
    """Stop the managed gateway and emit the CLI result."""

    run_lifecycle_action_for_cli(
        "stop",
        port=port,
        bind=bind,
        listen=listen,
        shutdown_timeout=shutdown_timeout,
        json_output=json_output,
    )


def restart_gateway_for_cli(
    *,
    port: int,
    bind: str,
    listen: str,
    health_timeout: float,
    shutdown_timeout: float,
    json_output: bool,
) -> None:
    """Restart the managed gateway and emit the CLI result."""

    run_lifecycle_action_for_cli(
        "restart",
        port=port,
        bind=bind,
        listen=listen,
        health_timeout=health_timeout,
        shutdown_timeout=shutdown_timeout,
        json_output=json_output,
    )
