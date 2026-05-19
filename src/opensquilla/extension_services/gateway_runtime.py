"""Gateway-facing runtime composition for extension services.

This module owns the boot-time integration seam for OpenSquilla extension
services: skills/plugins, memory, search, and scheduler.  Gateway boot remains
responsible for service ordering and container assembly, while this boundary
owns the domain-specific side effects needed to initialize the extension
services as one coherent subsystem.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger(__name__)


@dataclass
class ExtensionServicesRuntime:
    """Boot products owned by the extension-services boundary."""

    memory_managers: dict[str, Any] = field(default_factory=dict)
    memory_stores: dict[str, Any] = field(default_factory=dict)
    memory_retrievers: dict[str, Any] = field(default_factory=dict)
    memory_sync_managers: dict[str, Any] = field(default_factory=dict)
    turn_capture_services: dict[str, Any] = field(default_factory=dict)
    memory_watchers: list[Any] = field(default_factory=list)
    skill_loader: Any | None = None
    cron_scheduler: Any | None = None
    turn_runner_ref: list[Any] = field(default_factory=list)


async def build_extension_services_runtime(
    *,
    config: Any,
    tool_registry: Any,
    session_storage: Any,
    agent_ids: Sequence[str],
    state_path_factory: Callable[[Any, str], Path],
    logger: Any | None = None,
) -> ExtensionServicesRuntime:
    """Initialize extension-service runtime products for Gateway boot.

    The function intentionally preserves the fail-open boot policy previously
    owned inline by ``gateway.boot.build_services``: memory, skills, scheduler,
    and search failures are logged independently and do not prevent other
    extension services from initializing.
    """

    runtime = ExtensionServicesRuntime()
    logger = logger or log

    await _initialize_memory_runtime(
        runtime,
        config=config,
        tool_registry=tool_registry,
        agent_ids=list(agent_ids),
        logger=logger,
    )
    _initialize_skill_runtime(runtime, config=config, logger=logger)
    await _initialize_scheduler_runtime(
        runtime,
        config=config,
        session_storage=session_storage,
        state_path_factory=state_path_factory,
        logger=logger,
    )
    _initialize_search_runtime(config=config, logger=logger)
    return runtime


async def _initialize_memory_runtime(
    runtime: ExtensionServicesRuntime,
    *,
    config: Any,
    tool_registry: Any,
    agent_ids: list[str],
    logger: Any,
) -> None:
    try:
        from opensquilla.memory.gateway_runtime import build_memory_gateway_runtime

        memory_runtime = await build_memory_gateway_runtime(
            config=config,
            tool_registry=tool_registry,
            agent_ids=agent_ids,
            turn_runner_ref=runtime.turn_runner_ref,
        )
        runtime.memory_managers = memory_runtime.memory_managers
        runtime.memory_stores = memory_runtime.memory_stores
        runtime.memory_retrievers = memory_runtime.memory_retrievers
        runtime.memory_sync_managers = memory_runtime.memory_sync_managers
        runtime.turn_capture_services = memory_runtime.turn_capture_services
        runtime.memory_watchers = memory_runtime.memory_watchers
    except Exception as exc:  # noqa: BLE001 - preserve fail-open boot behavior
        logger.warning("build_services.memory_tools_failed", error=str(exc))


def _initialize_skill_runtime(
    runtime: ExtensionServicesRuntime,
    *,
    config: Any,
    logger: Any,
) -> None:
    try:
        from opensquilla.skills.runtime import create_configured_skill_loader

        skill_setup = create_configured_skill_loader(
            config.skills,
            workspace_dir=getattr(config, "workspace_dir", None),
        )
        runtime.skill_loader = skill_setup.loader
        logger.info(
            "build_services.skill_loader_initialized",
            bundled_dir=str(skill_setup.layer_dirs.bundled_dir),
        )

        from opensquilla.tools.builtin.skill_tools import create_skill_tools

        create_skill_tools(runtime.skill_loader)
        logger.info("build_services.skill_tools_registered")
    except Exception as exc:  # noqa: BLE001 - preserve fail-open boot behavior
        logger.warning("build_services.skill_loader_failed", error=str(exc))


async def _initialize_scheduler_runtime(
    runtime: ExtensionServicesRuntime,
    *,
    config: Any,
    session_storage: Any,
    state_path_factory: Callable[[Any, str], Path],
    logger: Any,
) -> None:
    try:
        from opensquilla.scheduler import JobStore, SchedulerEngine

        scheduler_db = Path(
            os.environ.get(
                "OPENSQUILLA_SCHEDULER_DB",
                str(state_path_factory(config, "scheduler.db")),
            )
        )
        scheduler_db.parent.mkdir(parents=True, exist_ok=True)
        job_store = JobStore(db_path=str(scheduler_db))
        await job_store.open()
        runtime.cron_scheduler = SchedulerEngine(
            store=job_store,
            session_store=session_storage,
            config={
                "max_concurrent_runs": int(
                    os.environ.get("OPENSQUILLA_CRON_MAX_CONCURRENT", "3")
                ),
                "max_catchup_jobs": int(os.environ.get("OPENSQUILLA_CRON_MAX_CATCHUP", "5")),
                "session_retention": int(
                    os.environ.get("OPENSQUILLA_CRON_SESSION_RETENTION", "86400")
                ),
            },
        )
        await runtime.cron_scheduler.start()
        from opensquilla.tools.services import configure_tool_services

        configure_tool_services(scheduler=runtime.cron_scheduler)
        logger.info("build_services.cron_scheduler_started")
    except Exception as exc:  # noqa: BLE001 - preserve fail-open boot behavior
        logger.warning("build_services.cron_scheduler_failed", error=str(exc))


def _initialize_search_runtime(*, config: Any, logger: Any) -> None:
    try:
        from opensquilla.search.runtime import sync_search_runtime_from_config

        runtime = sync_search_runtime_from_config(config)
        logger.info("build_services.search_provider_initialized", provider=runtime.provider_name)
    except Exception as exc:  # noqa: BLE001 - preserve fail-open boot behavior
        logger.warning("build_services.search_provider_failed", error=str(exc))


__all__ = [
    "ExtensionServicesRuntime",
    "build_extension_services_runtime",
]
