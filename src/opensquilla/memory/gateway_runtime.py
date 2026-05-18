"""Gateway boot runtime assembly for memory services."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from opensquilla.memory.manager import MemoryManager
    from opensquilla.tools.registry import ToolRegistry

log = structlog.get_logger(__name__)


@dataclass(slots=True)
class MemoryGatewayRuntime:
    """Gateway-facing memory runtime bundle.

    ``memory_managers`` is the owning source of truth. The remaining
    collections are legacy views kept for downstream boot consumers that have
    not migrated to managers yet.
    """

    memory_managers: dict[str, MemoryManager] = field(default_factory=dict)
    memory_stores: dict[str, Any] = field(default_factory=dict)
    memory_retrievers: dict[str, Any] = field(default_factory=dict)
    memory_sync_managers: dict[str, Any] = field(default_factory=dict)
    turn_capture_services: dict[str, Any] = field(default_factory=dict)
    memory_watchers: list[Any] = field(default_factory=list)
    turn_runner_ref: list[Any] = field(default_factory=list)


async def build_memory_gateway_runtime(
    *,
    config: Any,
    tool_registry: ToolRegistry,
    agent_ids: list[str],
    turn_runner_ref: list[Any] | None = None,
) -> MemoryGatewayRuntime:
    """Build memory managers, legacy views, and registered memory tools.

    The caller owns fail-open handling. This helper owns the memory-domain
    assembly previously embedded in gateway boot so boot can remain a thin
    coordinator.
    """
    from opensquilla.memory.manager import build_memory_managers
    from opensquilla.tools.builtin.memory_tools import create_memory_tools

    memory_managers = await build_memory_managers(config, agent_ids)
    runtime = _runtime_from_managers(
        memory_managers,
        turn_runner_ref=turn_runner_ref,
    )

    if runtime.memory_stores and runtime.memory_retrievers:
        create_memory_tools(
            stores=runtime.memory_stores,
            retrievers=runtime.memory_retrievers,
            memory_base=config.state_dir,
            registry=tool_registry,
            memory_source=getattr(config.memory, "source", "state"),
            on_memory_write=_memory_write_callback(runtime.turn_runner_ref),
            memory_config=config.memory,
            workspace_base=config.workspace_dir
            if getattr(config.memory, "source", "state") == "workspace"
            else None,
        )
        log.info(
            "build_services.memory_tools_registered",
            agents=list(runtime.memory_stores),
        )

    return runtime


def _runtime_from_managers(
    memory_managers: dict[str, MemoryManager],
    *,
    turn_runner_ref: list[Any] | None = None,
) -> MemoryGatewayRuntime:
    return MemoryGatewayRuntime(
        memory_managers=memory_managers,
        memory_stores={aid: manager.store for aid, manager in memory_managers.items()},
        memory_retrievers={
            aid: manager.retriever for aid, manager in memory_managers.items()
        },
        memory_sync_managers={
            aid: manager.sync_manager for aid, manager in memory_managers.items()
        },
        turn_capture_services={
            aid: manager.turn_capture for aid, manager in memory_managers.items()
        },
        memory_watchers=[manager.sync_manager for manager in memory_managers.values()],
        turn_runner_ref=turn_runner_ref if turn_runner_ref is not None else [],
    )


def _memory_write_callback(turn_runner_ref: list[Any]) -> Any:
    def _on_memory_write(agent_id: str) -> None:
        if turn_runner_ref:
            turn_runner_ref[0].refresh_memory_snapshot(agent_id)

    return _on_memory_write
