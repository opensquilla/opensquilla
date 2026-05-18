"""Gateway runtime startup wiring for task, heartbeat, and completion services."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from opensquilla.gateway.background_completion import BackgroundCompletionManager
from opensquilla.gateway.event_bridge import EventBridge
from opensquilla.gateway.subagent_announce import (
    announce_subagent_completion,
    set_background_completion_manager,
)
from opensquilla.gateway.task_runtime import TaskRun, TaskRuntime
from opensquilla.gateway.websocket import get_registry
from opensquilla.scheduler.heartbeat import HeartbeatConfigWatcher, HeartbeatRunner
from opensquilla.scheduler.heartbeat_loop import HeartbeatLoop
from opensquilla.scheduler.heartbeat_service import HeartbeatService
from opensquilla.session.services import get_session_storage
from opensquilla.tools.services import configure_tool_services

TaskTurnDispatcher = Callable[..., Awaitable[None]]


@dataclass
class GatewayRuntimeWiring:
    """Runtime services created during gateway boot and consumed by later wiring."""

    heartbeat_service: Any
    heartbeat_loop: Any
    heartbeat_watcher: Any
    task_runtime: Any
    runtime_event_bridge: Any
    background_completion_manager: Any


def _task_runtime_max_concurrency(config: Any) -> int:
    return int(config.task_runtime.max_concurrency)


def _task_runtime_max_pending_per_session(config: Any) -> int:
    return int(config.task_runtime.max_pending_per_session)


def _heartbeat_md_path(config: Any) -> Path:
    workspace_dir = config.workspace_dir or ""
    md_path_setting = getattr(config.heartbeat, "config_path", None)
    if md_path_setting:
        return Path(md_path_setting).expanduser()
    if workspace_dir:
        return Path(workspace_dir).expanduser() / "HEARTBEAT.md"
    return Path.home() / ".opensquilla" / "workspace" / "HEARTBEAT.md"


async def build_gateway_runtime_wiring(
    *,
    config: Any,
    svc: Any,
    turn_runner: Any,
    subscription_manager: Any,
    channel_manager_ref: Callable[[], Any | None],
    task_turn_dispatcher: TaskTurnDispatcher,
    connection_registry: Any | None = None,
) -> GatewayRuntimeWiring:
    """Build and attach gateway-owned runtime services.

    This keeps ``start_gateway_server`` focused on boot orchestration while
    preserving the runtime side effects that later cron, channel, and app
    construction depend on.
    """

    heartbeat_service = HeartbeatService(
        turn_runner=turn_runner,
        session_storage=get_session_storage(svc.session_manager) or svc.session_manager,
        channel_manager_ref=channel_manager_ref,
    )
    heartbeat_loop = HeartbeatLoop(
        config=config,
        heartbeat_service=heartbeat_service,
    )

    runtime_event_bridge = EventBridge(
        subscription_manager=subscription_manager,
        connection_registry=get_registry() if connection_registry is None else connection_registry,
    )
    background_completion_manager = BackgroundCompletionManager(
        session_manager=svc.session_manager,
        event_emitter=runtime_event_bridge.emit,
        channel_manager_ref=channel_manager_ref,
    )
    set_background_completion_manager(background_completion_manager)

    task_runtime: Any

    async def _subagent_completion_listener(event: Any) -> None:
        await announce_subagent_completion(
            event,
            session_manager=svc.session_manager,
            event_emitter=runtime_event_bridge.emit,
            channel_manager=channel_manager_ref(),
            task_runtime=task_runtime,
        )

    async def _task_runtime_turn_handler(run: TaskRun) -> None:
        await task_turn_dispatcher(
            run,
            config=config,
            session_manager=svc.session_manager,
            turn_runner=turn_runner,
            event_emitter=runtime_event_bridge.emit,
        )

    task_runtime = TaskRuntime(
        storage=get_session_storage(svc.session_manager) or svc.session_manager,
        turn_handler=_task_runtime_turn_handler,
        event_emitter=runtime_event_bridge.emit,
        terminal_listener=_subagent_completion_listener,
        max_concurrency=_task_runtime_max_concurrency(config),
        max_pending_per_session=_task_runtime_max_pending_per_session(config),
        subagent_reserved_slots=int(
            getattr(getattr(config, "subagents", None), "subagent_reserved_slots", 0)
        ),
    )
    turn_runner.set_session_lock_provider(task_runtime._get_session_lock_for_turn)
    svc.task_runtime = task_runtime

    attach_runtime = getattr(svc.session_manager, "attach_task_runtime", None)
    if callable(attach_runtime):
        attach_runtime(task_runtime)
    configure_tool_services(task_runtime=task_runtime)

    heartbeat_runner = HeartbeatRunner()
    heartbeat_watcher = HeartbeatConfigWatcher(
        heartbeat_runner,
        _heartbeat_md_path(config),
        loop_listener=heartbeat_loop.apply_overrides,
    )
    await heartbeat_watcher.start()
    svc.heartbeat_watcher = heartbeat_watcher

    await heartbeat_loop.start()
    svc.heartbeat_loop = heartbeat_loop

    return GatewayRuntimeWiring(
        heartbeat_service=heartbeat_service,
        heartbeat_loop=heartbeat_loop,
        heartbeat_watcher=heartbeat_watcher,
        task_runtime=task_runtime,
        runtime_event_bridge=runtime_event_bridge,
        background_completion_manager=background_completion_manager,
    )
