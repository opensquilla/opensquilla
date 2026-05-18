"""In-memory state boundary for TaskRuntime."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Collection
from dataclasses import dataclass

from opensquilla.gateway.routing import RouteEnvelope
from opensquilla.gateway.task_runtime_records import RuntimeTask
from opensquilla.gateway.task_runtime_terminal_state import (
    TerminalStateCleanup,
    cleanup_terminal_task_state,
    snapshot_unfinished_tasks,
)
from opensquilla.session.models import AgentTaskStatus


@dataclass(frozen=True)
class CollectedTaskUpdate:
    task: RuntimeTask
    details: dict[str, object]


class TaskRuntimeState:
    """Own the runtime's process-local task indexes."""

    def __init__(self) -> None:
        self._tasks: dict[str, RuntimeTask] = {}
        self._pending_by_session: dict[str, list[RuntimeTask]] = {}
        self._running_by_session: dict[str, RuntimeTask] = {}
        self._last_envelope_by_session: dict[str, RouteEnvelope] = {}
        self._state_lock = asyncio.Lock()

    @property
    def tasks(self) -> dict[str, RuntimeTask]:
        return self._tasks

    @property
    def pending_by_session(self) -> dict[str, list[RuntimeTask]]:
        return self._pending_by_session

    @property
    def running_by_session(self) -> dict[str, RuntimeTask]:
        return self._running_by_session

    @property
    def last_envelope_by_session(self) -> dict[str, RouteEnvelope]:
        return self._last_envelope_by_session

    @property
    def state_lock(self) -> asyncio.Lock:
        return self._state_lock

    def get_task(self, task_id: str) -> RuntimeTask | None:
        return self._tasks.get(task_id)

    def get_last_envelope(self, session_key: str) -> RouteEnvelope | None:
        return self._last_envelope_by_session.get(session_key)

    def pending_count(self, session_key: str) -> int:
        return len(self._pending_by_session.get(session_key, []))

    async def pending_count_locked(self, session_key: str) -> int:
        async with self._state_lock:
            return self.pending_count(session_key)

    async def try_collect(
        self,
        *,
        envelope: RouteEnvelope,
        message: str,
        run_kind: str,
        no_memory_capture: bool,
    ) -> CollectedTaskUpdate | None:
        async with self._state_lock:
            pending = self._pending_by_session.get(envelope.session_key, [])
            candidate = next(
                (
                    task
                    for task in reversed(pending)
                    if task.queue_mode == "collect" and task.status == AgentTaskStatus.QUEUED
                ),
                None,
            )
            if candidate is None:
                return None
            if (
                no_memory_capture
                or candidate.run_kind != run_kind
                or candidate.envelope.input_provenance != envelope.input_provenance
            ):
                candidate.no_memory_capture = True
            candidate.message = f"{candidate.message}\n{message}"
            details: dict[str, object] = {
                "source_name": candidate.envelope.source_name,
                "input_provenance": candidate.envelope.input_provenance,
                "metadata": candidate.envelope.metadata,
                "collected": True,
                "message_count": candidate.message.count("\n") + 1,
                "no_memory_capture": candidate.no_memory_capture,
            }
        return CollectedTaskUpdate(task=candidate, details=details)

    async def register_queued(
        self,
        task: RuntimeTask,
        *,
        update_envelope_cache: bool,
        before_start: Callable[[], None],
        start_task: Callable[[], asyncio.Task[None]],
    ) -> int:
        async with self._state_lock:
            self._tasks[task.task_id] = task
            self._pending_by_session.setdefault(task.envelope.session_key, []).append(task)
            if update_envelope_cache:
                self._last_envelope_by_session[task.envelope.session_key] = task.envelope
            before_start()
            task.asyncio_task = start_task()
            return self.pending_count(task.envelope.session_key)

    async def cancel_matching(
        self,
        *,
        task_id: str | None,
        session_key: str | None,
        terminal_statuses: Collection[AgentTaskStatus],
    ) -> int:
        async with self._state_lock:
            tasks = [
                task
                for task in self._tasks.values()
                if (task_id is None or task.task_id == task_id)
                and (session_key is None or task.envelope.session_key == session_key)
                and task.status not in terminal_statuses
            ]
            for task in tasks:
                task.cancel_requested = True
                if task.asyncio_task is not None and not task.asyncio_task.done():
                    task.asyncio_task.cancel()
        return len(tasks)

    async def mark_running(self, task: RuntimeTask) -> None:
        async with self._state_lock:
            task.status = AgentTaskStatus.RUNNING
            self._remove_pending(task)
            self._running_by_session[task.envelope.session_key] = task

    async def cleanup_terminal(
        self,
        *,
        task: RuntimeTask,
        status: AgentTaskStatus,
        after_cleanup: Callable[[TerminalStateCleanup], None] | None = None,
    ) -> TerminalStateCleanup:
        async with self._state_lock:
            cleanup = cleanup_terminal_task_state(
                task=task,
                status=status,
                tasks=self._tasks,
                pending_by_session=self._pending_by_session,
                running_by_session=self._running_by_session,
                last_envelope_by_session=self._last_envelope_by_session,
            )
            if cleanup.emitted and after_cleanup is not None:
                after_cleanup(cleanup)
            return cleanup

    async def snapshot_unfinished(self) -> list[RuntimeTask]:
        async with self._state_lock:
            return snapshot_unfinished_tasks(self._tasks)

    def _remove_pending(self, task: RuntimeTask) -> None:
        pending = self._pending_by_session.get(task.envelope.session_key)
        if not pending:
            return
        try:
            pending.remove(task)
        except ValueError:
            return
        if not pending:
            self._pending_by_session.pop(task.envelope.session_key, None)


__all__ = [
    "CollectedTaskUpdate",
    "TaskRuntimeState",
]
