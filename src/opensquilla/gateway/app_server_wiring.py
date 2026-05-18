"""Gateway ASGI app and managed uvicorn server startup wiring."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import structlog
import uvicorn

from opensquilla.asyncio_utils import create_background_task
from opensquilla.gateway.app import create_gateway_app
from opensquilla.gateway.config import GatewayConfig, is_public_bind

log = structlog.get_logger(__name__)

_PUBLIC_BIND_MESSAGE = (
    "gateway bound to a wildcard address; reachable from "
    "every interface. Opt-in required — only expose behind "
    "a trusted reverse proxy or VPN."
)


def build_gateway_app_server(
    *,
    config: GatewayConfig,
    svc: Any,
    subscription_manager: Any,
    channel_manager: Any,
    turn_runner: Any,
    task_runtime: Any,
    heartbeat_service: Any,
    heartbeat_loop: Any,
    background_completion_manager: Any,
    diagnostics_state: Any | None,
    webhook_routes: list[Any],
    run: bool,
    gateway_server_factory: Callable[..., Any],
    create_gateway_app_fn: Callable[..., Any] = create_gateway_app,
    uvicorn_config_factory: Callable[..., Any] = uvicorn.Config,
    uvicorn_server_factory: Callable[[Any], Any] = uvicorn.Server,
    background_task_factory: Callable[[Any], Any] = create_background_task,
    public_bind_checker: Callable[[str], bool] = is_public_bind,
    logger: Any = log,
) -> Any:
    """Build the Gateway ASGI app and optional managed uvicorn server handle."""

    app = create_gateway_app_fn(
        config,
        session_manager=svc.session_manager,
        provider_selector=svc.provider_selector,
        tool_registry=svc.tool_registry,
        subscription_manager=subscription_manager,
        channel_manager=channel_manager,
        usage_tracker=svc.usage_tracker,
        skill_loader=svc.skill_loader,
        cron_scheduler=svc.cron_scheduler,
        turn_runner=turn_runner,
        task_runtime=task_runtime,
        flush_service=svc.flush_service,
        heartbeat_service=heartbeat_service,
        heartbeat_loop=heartbeat_loop,
        agent_registry=svc.agent_registry,
        diagnostics_state=diagnostics_state,
        memory_managers=svc.memory_managers,
        memory_stores=svc.memory_stores,
        memory_retrievers=svc.memory_retrievers,
        extra_routes=webhook_routes or None,
    )
    app.state.gateway_ready = False

    server_handle = gateway_server_factory(app=app, config=config)
    server_handle._channel_manager = channel_manager
    server_handle._services = svc
    server_handle._background_completion_manager = background_completion_manager

    if run:
        uv_config = uvicorn_config_factory(
            app=app,
            host=config.host,
            port=config.port,
            log_level="info" if not config.debug else "debug",
        )
        server = uvicorn_server_factory(uv_config)
        server_handle._server = server

        task = background_task_factory(server.serve())
        server_handle._task = task

        # Warn loudly before the normal started line so operators
        # see the network-exposure notice even on info-level log streams.
        if public_bind_checker(config.host):
            logger.warning(
                "gateway.bind.public",
                host=config.host,
                port=config.port,
                message=_PUBLIC_BIND_MESSAGE,
            )
        logger.info("gateway.started", host=config.host, port=config.port)

    return server_handle
