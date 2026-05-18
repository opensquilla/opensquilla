"""Gateway channel manager construction and startup wiring."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import structlog

from opensquilla.channels.manager import ChannelManager
from opensquilla.gateway.channel_ingress import GatewayChannelIngress
from opensquilla.gateway.rpc import get_dispatcher

log = structlog.get_logger(__name__)


@dataclass
class GatewayChannelManagerWiring:
    """Channel manager and webhook routes produced during gateway boot."""

    channel_manager: Any
    webhook_routes: list[Any]


def build_gateway_channel_manager_wiring(
    *,
    config: Any,
    svc: Any,
    turn_runner: Any,
    subscription_manager: Any,
    channel_manager: Any,
    channel_manager_ref: Callable[[], Any | None],
    set_channel_manager_ref: Callable[[Any], None],
    runtime_event_bridge: Any,
    task_runtime: Any,
    heartbeat_service: Any,
    diagnostics_state: Any | None,
    channel_rpc_context_factory_builder: Callable[..., Any],
    logger: Any = log,
) -> GatewayChannelManagerWiring:
    """Build gateway channel manager dependencies while preserving boot behavior."""

    if channel_manager is not None:
        set_channel_manager_ref(channel_manager)
        return GatewayChannelManagerWiring(
            channel_manager=channel_manager,
            webhook_routes=[],
        )

    channel_entries = config.channels.channels
    if not channel_entries:
        return GatewayChannelManagerWiring(
            channel_manager=None,
            webhook_routes=[],
        )

    channel_rpc_context_factory = channel_rpc_context_factory_builder(
        svc,
        config,
        subscription_manager=subscription_manager,
        channel_manager_ref=channel_manager_ref,
        turn_runner=turn_runner,
        heartbeat_service=heartbeat_service,
        diagnostics_state=diagnostics_state,
    )
    channel_manager = ChannelManager.from_config(
        channel_entries,
        turn_runner=turn_runner,
        session_manager=svc.session_manager,
        event_bridge=runtime_event_bridge,
        config=config,
        task_runtime=task_runtime,
        rpc_dispatcher=get_dispatcher(),
        channel_rpc_context_factory=channel_rpc_context_factory,
        channel_ingress=GatewayChannelIngress(),
    )
    webhook_routes = channel_manager.collect_webhook_routes()
    set_channel_manager_ref(channel_manager)
    logger.info(
        "gateway.channels_built",
        count=len(channel_entries),
        webhooks=len(webhook_routes),
    )
    return GatewayChannelManagerWiring(
        channel_manager=channel_manager,
        webhook_routes=webhook_routes,
    )


async def start_gateway_channels(channel_manager: Any, *, logger: Any = log) -> None:
    """Start configured gateway channels and preserve existing startup logs."""

    if channel_manager is None:
        return

    results = await channel_manager.start_all()
    start_errors_fn = getattr(channel_manager, "start_errors", None)
    start_errors = start_errors_fn() if start_errors_fn is not None else {}
    for name, ok in results.items():
        if ok:
            logger.info("gateway.channel_started", channel=name)
        else:
            details = start_errors.get(name, {})
            logger.warning(
                "gateway.channel_failed",
                channel=name,
                error_type=details.get("error_type"),
                error=details.get("error"),
                exception=details.get("exception"),
            )
