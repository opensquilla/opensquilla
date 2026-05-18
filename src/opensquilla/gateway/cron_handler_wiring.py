"""Gateway cron handler registration wiring."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from opensquilla.agents.scope import resolve_agent_workspace_dir
from opensquilla.gateway.config import GatewayConfig
from opensquilla.gateway.cron_result_delivery import build_cron_delivery_chain
from opensquilla.gateway.session_event_delivery import deliver_session_event
from opensquilla.gateway.websocket import get_registry
from opensquilla.memory.dream_factory import build_dream_factory
from opensquilla.scheduler.dream_handler import make_memory_dream_handler
from opensquilla.scheduler.handlers import make_agent_run_handler, make_system_event_handler


async def register_gateway_cron_handlers(
    *,
    config: GatewayConfig,
    svc: Any,
    turn_runner: Any,
    task_runtime: Any,
    heartbeat_service: Any,
    heartbeat_loop: Any,
    subscription_manager: Any,
    channel_manager_ref: Callable[[], Any],
    dream_cron_registrar: Callable[..., Any],
    configured_agent_ids: Callable[[GatewayConfig], list[str]],
    logger: Any,
    deliver_session_event_fn: Callable[..., Any] = deliver_session_event,
    connection_registry_getter: Callable[[], Any] = get_registry,
) -> None:
    """Register gateway-owned scheduler handlers and Dream cron schedules."""
    cron_scheduler = getattr(svc, "cron_scheduler", None)
    if cron_scheduler is None:
        return

    async def _emit_session_event(
        session_key: str,
        event_name: str,
        payload: dict[str, Any],
    ) -> None:
        if subscription_manager is None:
            return

        await deliver_session_event_fn(
            subscription_manager=subscription_manager,
            connection_registry=connection_registry_getter(),
            session_key=session_key,
            event_name=event_name,
            payload=payload,
            logger=logger,
        )

    delivery_chain = build_cron_delivery_chain(
        channel_manager_ref=channel_manager_ref,
        subscription_manager=subscription_manager,
        session_manager=svc.session_manager,
    )

    def _cron_workspace_resolver(agent_id: str) -> tuple[str | None, bool]:
        workspace_dir = resolve_agent_workspace_dir(agent_id, config)
        workspace_strict = getattr(config, "workspace_strict", None)
        if not isinstance(workspace_strict, bool):
            workspace_strict = bool(workspace_dir)
        return str(workspace_dir), workspace_strict

    agent_handler = make_agent_run_handler(
        delivery_chain=delivery_chain,
        turn_runner_ref=lambda: turn_runner,
        session_manager_ref=lambda: svc.session_manager,
        task_runtime_ref=lambda: task_runtime,
        workspace_resolver=_cron_workspace_resolver,
    )
    system_handler = make_system_event_handler(
        delivery_chain=delivery_chain,
        turn_runner_ref=lambda: turn_runner,
        session_manager_ref=lambda: svc.session_manager,
        session_event_emitter=_emit_session_event,
        heartbeat_service_ref=lambda: heartbeat_service,
        heartbeat_loop_ref=lambda: heartbeat_loop,
        workspace_resolver=_cron_workspace_resolver,
    )
    dream_handler = make_memory_dream_handler(
        build_dream=build_dream_factory(
            config=config,
            provider_selector=svc.provider_selector,
            tool_registry=svc.tool_registry,
            turn_runner=turn_runner,
        ),
        should_skip=lambda: (
            "disabled" if not getattr(config.memory.dream, "enabled", False) else None
        ),
    )
    cron_scheduler.register_handler("agent_run", agent_handler)
    cron_scheduler.register_handler("system_event", system_handler)
    cron_scheduler.register_handler("memory_dream", dream_handler)
    logger.info("gateway.cron_handler_registered", handler_key="agent_run")
    logger.info("gateway.cron_handler_registered", handler_key="system_event")
    logger.info("gateway.cron_handler_registered", handler_key="memory_dream")
    await dream_cron_registrar(
        scheduler=cron_scheduler,
        memory_config=config.memory,
        agent_ids=configured_agent_ids(config),
    )
