"""Terminal state cleanup helpers for the in-process task runtime."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from opensquilla.gateway.routing import RouteEnvelope
from opensquilla.gateway.task_runtime_records import RuntimeTask
from opensquilla.session.models import AgentTaskStatus

TERMINAL_STATUSES = frozenset(
    {
        AgentTaskStatus.SUCCEEDED,
        AgentTaskStatus.FAILED,
        AgentTaskStatus.CANCELLED,
        AgentTaskStatus.TIMEOUT,
        AgentTaskStatus.ABANDONED,
    }
)


@dataclass(frozen=True)
class TerminalStateCleanup:
    """Result of a terminal cleanup attempt."""

    emitted: bool
    has_session_work: bool


def cleanup_terminal_task_state(
    *,
    task: RuntimeTask,
    status: AgentTaskStatus,
    tasks: dict[str, RuntimeTask],
    pending_by_session: dict[str, list[RuntimeTask]],
    running_by_session: dict[str, RuntimeTask],
    last_envelope_by_session: dict[str, RouteEnvelope],
) -> TerminalStateCleanup:
    """Mark a task terminal and remove its short-lived runtime state."""
    if task.terminal_emitted:
        return TerminalStateCleanup(emitted=False, has_session_work=True)
    task.terminal_emitted = True
    task.status = status
    _remove_pending_task(pending_by_session, task)
    session_key = task.envelope.session_key
    if running_by_session.get(session_key) is task:
        running_by_session.pop(session_key, None)
    tasks.pop(task.task_id, None)
    last_envelope_by_session.pop(session_key, None)
    return TerminalStateCleanup(
        emitted=True,
        has_session_work=bool(pending_by_session.get(session_key))
        or running_by_session.get(session_key) is not None,
    )


def snapshot_unfinished_tasks(
    tasks: Mapping[str, RuntimeTask],
) -> list[RuntimeTask]:
    """Return a stable snapshot of tasks that have not reached terminal state."""
    return [task for task in tasks.values() if task.status not in TERMINAL_STATUSES]


def _remove_pending_task(
    pending_by_session: dict[str, list[RuntimeTask]],
    task: RuntimeTask,
) -> None:
    pending = pending_by_session.get(task.envelope.session_key)
    if not pending:
        return
    try:
        pending.remove(task)
    except ValueError:
        return
    if not pending:
        pending_by_session.pop(task.envelope.session_key, None)


__all__ = [
    "TERMINAL_STATUSES",
    "TerminalStateCleanup",
    "cleanup_terminal_task_state",
    "snapshot_unfinished_tasks",
]
