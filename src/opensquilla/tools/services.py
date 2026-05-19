"""Shared service handles used by builtin tools.

The gateway composition root owns these references. Individual builtin tool
modules keep compatibility setter functions, but those functions delegate here
instead of storing their own service globals.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Final, cast

from opensquilla.tools.types import ToolError

SpawnGroupCloser = Callable[..., Awaitable[bool]]


@dataclass
class ToolServices:
    session_manager: object | None = None
    task_runtime: object | None = None
    gateway_config: object | None = None
    spawn_group_closer: SpawnGroupCloser | None = None
    agent_registry: object | None = None
    scheduler: object | None = None


_UNSET: Final = object()
_services = ToolServices()


def configure_tool_services(
    *,
    session_manager: Any = _UNSET,
    task_runtime: Any = _UNSET,
    gateway_config: Any = _UNSET,
    spawn_group_closer: Any = _UNSET,
    agent_registry: Any = _UNSET,
    scheduler: Any = _UNSET,
) -> ToolServices:
    """Update one or more builtin-tool service handles."""

    if session_manager is not _UNSET:
        _services.session_manager = cast(object | None, session_manager)
    if task_runtime is not _UNSET:
        _services.task_runtime = cast(object | None, task_runtime)
    if gateway_config is not _UNSET:
        _services.gateway_config = cast(object | None, gateway_config)
    if spawn_group_closer is not _UNSET:
        _services.spawn_group_closer = cast(SpawnGroupCloser | None, spawn_group_closer)
    if agent_registry is not _UNSET:
        _services.agent_registry = cast(object | None, agent_registry)
    if scheduler is not _UNSET:
        _services.scheduler = cast(object | None, scheduler)
    return _services


def reset_tool_services() -> None:
    """Clear all service handles. Intended for tests and controlled shutdown."""

    configure_tool_services(
        session_manager=None,
        task_runtime=None,
        gateway_config=None,
        spawn_group_closer=None,
        agent_registry=None,
        scheduler=None,
    )


def current_tool_services() -> ToolServices:
    return _services


def set_session_manager(mgr: object | None) -> None:
    configure_tool_services(session_manager=mgr)


def set_task_runtime(runtime: object | None) -> None:
    configure_tool_services(task_runtime=runtime)


def set_gateway_config(config: object | None) -> None:
    configure_tool_services(gateway_config=config)


def set_spawn_group_closer(closer: SpawnGroupCloser | None) -> None:
    configure_tool_services(spawn_group_closer=closer)


def set_agent_registry(registry: object | None) -> None:
    configure_tool_services(agent_registry=registry)


def set_scheduler(scheduler: object | None) -> None:
    configure_tool_services(scheduler=scheduler)


def session_manager_available() -> bool:
    return _services.session_manager is not None


def task_runtime_available() -> bool:
    return _services.task_runtime is not None


def gateway_config_available() -> bool:
    return _services.gateway_config is not None


def scheduler_available() -> bool:
    return _services.scheduler is not None


def get_session_manager() -> object:
    if _services.session_manager is None:
        raise ToolError("Session manager not available")
    return _services.session_manager


def get_task_runtime() -> object:
    if _services.task_runtime is None:
        raise ToolError("Task runtime not available")
    return _services.task_runtime


def get_gateway_config() -> object:
    if _services.gateway_config is None:
        raise ToolError("Gateway config not available")
    return _services.gateway_config


def get_optional_gateway_config() -> object | None:
    return _services.gateway_config


def get_spawn_group_closer() -> SpawnGroupCloser | None:
    return _services.spawn_group_closer


def get_agent_registry() -> object:
    if _services.agent_registry is None:
        raise ToolError("Agent registry not available")
    return _services.agent_registry


def get_scheduler() -> object:
    if _services.scheduler is None:
        raise ToolError("Scheduler not available")
    return _services.scheduler
