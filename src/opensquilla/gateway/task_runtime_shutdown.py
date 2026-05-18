"""Shutdown orchestration for TaskRuntime."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping

import structlog

from opensquilla.gateway.task_runtime_records import RuntimeTask

log = structlog.get_logger(__name__)

MarkUnfinishedAbandoned = Callable[[], Awaitable[None]]


async def shutdown_task_runtime(
    *,
    tasks: Mapping[str, RuntimeTask],
    state_lock: asyncio.Lock,
    mark_unfinished_abandoned: MarkUnfinishedAbandoned,
    cancel: bool = True,
    timeout: float = 5.0,
    graceful: bool = False,
    graceful_timeout: float | None = None,
) -> None:
    """Shut down in-flight runtime tasks with optional graceful drain."""
    active_tasks = await _snapshot_active_asyncio_tasks(tasks=tasks, state_lock=state_lock)
    if not active_tasks:
        return

    if graceful:
        try:
            await asyncio.wait_for(
                asyncio.gather(*active_tasks, return_exceptions=True),
                timeout=graceful_timeout,
            )
            return
        except TimeoutError:
            log.warning(
                "task_runtime.graceful_shutdown_timeout",
                graceful_timeout=graceful_timeout,
                remaining=sum(1 for task in active_tasks if not task.done()),
            )
        active_tasks = [task for task in active_tasks if not task.done()]

    if cancel:
        for task in active_tasks:
            task.cancel()
    if active_tasks:
        done, pending = await asyncio.wait(active_tasks, timeout=timeout)
        for task in pending:
            task.cancel()
        if pending:
            await mark_unfinished_abandoned()
        for task in done:
            try:
                task.result()
            except (asyncio.CancelledError, Exception):
                pass


async def _snapshot_active_asyncio_tasks(
    *,
    tasks: Mapping[str, RuntimeTask],
    state_lock: asyncio.Lock,
) -> list[asyncio.Task[None]]:
    async with state_lock:
        return [
            task.asyncio_task
            for task in tasks.values()
            if task.asyncio_task is not None and not task.asyncio_task.done()
        ]
