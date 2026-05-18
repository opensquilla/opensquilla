"""TaskRuntime execution lifecycle coordinator."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

from opensquilla.gateway.task_runtime_records import RuntimeTask, TaskHandler, TaskRun
from opensquilla.session.models import AgentTaskStatus


class _MarkTerminal(Protocol):
    async def __call__(
        self,
        task: RuntimeTask,
        status: AgentTaskStatus,
        *,
        terminal_reason: str,
        error_class: str | None = None,
        error_message: str | None = None,
    ) -> None: ...


@dataclass(frozen=True)
class TaskRuntimeExecutionCallbacks:
    wait_for_subagent_slot: Callable[[RuntimeTask], Awaitable[None]]
    acquire_fair_slot: Callable[[RuntimeTask], Awaitable[None]]
    release_slot: Callable[[RuntimeTask], Awaitable[None]]
    mark_terminal: _MarkTerminal
    turn_handler: TaskHandler
    emit_metric: Callable[..., None]


async def execute_task_lifecycle(
    *,
    task: RuntimeTask,
    session_lock: asyncio.Lock,
    callbacks: TaskRuntimeExecutionCallbacks,
) -> None:
    try:
        async with session_lock:
            # Signal to TurnRunner.run() that this Task already holds the
            # session lock so run() can skip re-acquisition without using
            # lock.locked() (which cannot distinguish owners across tasks).
            from opensquilla.engine.runtime import _SESSION_LOCK_OWNER

            current_task = asyncio.current_task()
            prev_map = _SESSION_LOCK_OWNER.get(None)
            new_map: dict[int, Any] = dict(prev_map or {})
            if current_task is not None:
                new_map[id(session_lock)] = current_task
            owner_token = _SESSION_LOCK_OWNER.set(new_map)
            try:
                if task.cancel_requested:
                    callbacks.emit_metric(
                        "turn_cancellations_total",
                        value=1,
                        reason="user_cancel",
                        session_key=task.envelope.session_key,
                    )
                    await callbacks.mark_terminal(
                        task,
                        AgentTaskStatus.CANCELLED,
                        terminal_reason="cancelled_before_start",
                    )
                    return
                await callbacks.wait_for_subagent_slot(task)
                acquired = False
                try:
                    await callbacks.acquire_fair_slot(task)
                    acquired = True
                    await callbacks.turn_handler(_build_task_run(task))
                    await callbacks.mark_terminal(
                        task,
                        AgentTaskStatus.SUCCEEDED,
                        terminal_reason="completed",
                    )
                finally:
                    if acquired:
                        await callbacks.release_slot(task)
            finally:
                _SESSION_LOCK_OWNER.reset(owner_token)
    except asyncio.CancelledError:
        callbacks.emit_metric(
            "turn_cancellations_total",
            value=1,
            reason="interrupt",
            session_key=task.envelope.session_key,
        )
        await callbacks.mark_terminal(
            task,
            AgentTaskStatus.CANCELLED,
            terminal_reason="cancelled",
        )
    except TimeoutError as exc:
        callbacks.emit_metric(
            "turn_cancellations_total",
            value=1,
            reason="timeout",
            session_key=task.envelope.session_key,
        )
        await callbacks.mark_terminal(
            task,
            AgentTaskStatus.TIMEOUT,
            terminal_reason="timeout",
            error_class=type(exc).__name__,
            error_message=str(exc),
        )
    except Exception as exc:  # noqa: BLE001 - runtime ledger records the class.
        await callbacks.mark_terminal(
            task,
            AgentTaskStatus.FAILED,
            terminal_reason="error",
            error_class=type(exc).__name__,
            error_message=str(exc),
        )


def _build_task_run(task: RuntimeTask) -> TaskRun:
    return TaskRun(
        task_id=task.task_id,
        envelope=task.envelope,
        message=task.message,
        attachments=task.attachments,
        queue_mode=task.queue_mode,
        run_kind=task.run_kind,
        no_memory_capture=task.no_memory_capture,
        ingress_pipeline_steps=task.ingress_pipeline_steps,
        semantic_message=task.semantic_message,
        stream_event_sink=task.stream_event_sink,
    )


__all__ = [
    "TaskRuntimeExecutionCallbacks",
    "execute_task_lifecycle",
]
