"""In-process task runtime for agent turns.

Lock ordering invariant:
    Two independent per-session lock dictionaries exist in this process:

    1. ``TaskRuntime._session_locks`` (this module, line ~183)
       OUTER lock — serializes task dispatch within a session.  Acquired by
       ``_execute()`` before the turn handler is called.

    2. ``TurnRunner._session_locks`` (engine/runtime.py, ~line 900)
       INNER lock — serializes transcript writes and memory capture within a
       session.  Acquired by ``TurnRunner.run()`` which is invoked *inside*
       ``_execute()`` via the ``_turn_handler`` callback.

    Required acquire order: OUTER (TaskRuntime) then INNER (TurnRunner).
    DO NOT acquire ``TaskRuntime._session_locks[*]`` while already holding
    ``TurnRunner._session_locks[*]``; that reverse order would deadlock under
    contention.  The two locks protect disjoint concerns and must never be
    acquired in the wrong direction.
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import replace
from typing import Any, cast

import structlog

from opensquilla.gateway.routing import RouteEnvelope, SourceKind
from opensquilla.gateway.task_runtime_execution import (
    TaskRuntimeExecutionCallbacks,
    execute_task_lifecycle,
)
from opensquilla.gateway.task_runtime_records import (
    EventEmitter,
    TaskHandle,
    TaskHandler,
    TaskQueueFullError,
    TaskStreamEventSink,
    TerminalListener,
)
from opensquilla.gateway.task_runtime_records import (
    RuntimeTask as _RuntimeTask,
)
from opensquilla.gateway.task_runtime_scheduler import TaskRuntimeScheduler
from opensquilla.gateway.task_runtime_terminal import (
    SubagentCompletionEvent as SubagentCompletionEvent,
)
from opensquilla.gateway.task_runtime_terminal import (
    build_task_terminal_payload,
    notify_subagent_terminal,
)
from opensquilla.session.keys import canonicalize_session_key, normalize_agent_id, parse_agent_id
from opensquilla.session.models import AgentTaskRecord, AgentTaskStatus

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Core metrics — names are LOCKED. Do not rename without updating
# README "Observability: Core Metrics" and the corresponding CI grep.
#   opensquilla_queue_depth   (gauge)   — pending queue depth per session
#   in_flight_turns_total     (counter) — cumulative turns entering _execute
#   turn_cancellations_total  (counter) — cumulative cancel/interrupt/timeout
#   queue_full_errors_total   (counter) — cumulative TaskQueueFullError raises
# ---------------------------------------------------------------------------


def _emit_metric(name: str, value: int = 1, **labels: Any) -> None:
    """Emit a structured log line for a core metric.

    Format: event=<name> metric=<name> value=<int> [labels...]
    Grep pattern: ``metric=<name>``
    """
    log.info(name, metric=name, value=value, **labels)


TERMINAL_STATUSES = frozenset(
    {
        AgentTaskStatus.SUCCEEDED,
        AgentTaskStatus.FAILED,
        AgentTaskStatus.CANCELLED,
        AgentTaskStatus.TIMEOUT,
        AgentTaskStatus.ABANDONED,
    }
)


class TaskRuntime:
    """Serialize same-session turns while allowing cross-session concurrency.

    Lock ordering invariant:
        This class owns ``self._session_locks`` (the OUTER lock dict) to gate
        task dispatch: ``_execute()`` acquires the lock before invoking the
        turn handler, which eventually calls ``TurnRunner.run()`` and acquires
        the INNER lock (``TurnRunner._session_locks``).

        Required acquire order: OUTER (this class) → INNER (TurnRunner).
        DO NOT acquire ``self._session_locks[*]`` while holding
        ``TurnRunner._session_locks[*]``; reverse order deadlocks under
        contention.  The two dicts protect different scopes: this dict
        serializes queued-task dispatch; TurnRunner's dict serializes
        transcript writes and memory capture.
    """

    def __init__(
        self,
        *,
        storage: Any,
        turn_handler: TaskHandler,
        event_emitter: EventEmitter | None = None,
        terminal_listener: TerminalListener | None = None,
        max_concurrency: int = 4,
        max_pending_per_session: int | None = 64,
        subagent_reserved_slots: int = 0,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be >= 1")
        if max_pending_per_session is not None and max_pending_per_session < 1:
            raise ValueError("max_pending_per_session must be >= 1")
        if subagent_reserved_slots < 0:
            raise ValueError("subagent_reserved_slots must be >= 0")
        # Clamp so subagents can always acquire eventually. A reservation that
        # consumes the entire pool would deadlock the subagent lane.
        if subagent_reserved_slots >= max_concurrency:
            import structlog

            structlog.get_logger("opensquilla.gateway.task_runtime").warning(
                "task_runtime.subagent_reserved_slots_clamped",
                requested=subagent_reserved_slots,
                max_concurrency=max_concurrency,
                clamped_to=max(0, max_concurrency - 1),
            )
            subagent_reserved_slots = max(0, max_concurrency - 1)
        self._storage = storage
        self._turn_handler = turn_handler
        self._event_emitter = event_emitter
        self._terminal_listener = terminal_listener
        self._max_pending_per_session = max_pending_per_session
        self._scheduler = TaskRuntimeScheduler(
            max_concurrency=max_concurrency,
            subagent_reserved_slots=subagent_reserved_slots,
        )
        # OUTER per-session lock dict (see Lock ordering invariant in class docstring).
        # Protects: task dispatch serialization within a session — ensures at most
        # one task runs at a time per session_key.  Acquire order: always BEFORE
        # TurnRunner._session_locks when both are needed in the same call path.
        self._session_locks: dict[str, asyncio.Lock] = {}
        self._tasks: dict[str, _RuntimeTask] = {}
        self._pending_by_session: dict[str, list[_RuntimeTask]] = {}
        self._running_by_session: dict[str, _RuntimeTask] = {}
        self._last_envelope_by_session: dict[str, RouteEnvelope] = {}
        self._state_lock = asyncio.Lock()

    @property
    def _max_concurrency(self) -> int:
        return self._scheduler.max_concurrency

    @property
    def _subagent_reserved_slots(self) -> int:
        return self._scheduler.subagent_reserved_slots

    @property
    def _global_in_flight(self) -> int:
        return self._scheduler.global_in_flight

    @property
    def _subagent_in_flight(self) -> int:
        return self._scheduler.subagent_in_flight

    @property
    def _slot_cond(self) -> asyncio.Condition | None:
        return self._scheduler.slot_cond

    @property
    def _agent_session_rr(self) -> dict[str, deque[str]]:
        return self._scheduler.agent_session_rr

    @property
    def _agent_active_sessions(self) -> dict[str, set[str]]:
        return self._scheduler.agent_active_sessions

    @property
    def _agent_in_flight(self) -> dict[str, int]:
        return self._scheduler.agent_in_flight

    @property
    def _fair_cond(self) -> asyncio.Condition | None:
        return self._scheduler.fair_cond

    async def enqueue(
        self,
        envelope: RouteEnvelope,
        message: str,
        attachments: list[dict[str, Any]] | None = None,
        mode: str | None = None,
        run_kind: str = "default",
        no_memory_capture: bool = False,
        ingress_pipeline_steps: tuple[Any, ...] | list[Any] | None = None,
        semantic_message: str | None = None,
        stream_event_sink: TaskStreamEventSink | None = None,
        *,
        update_envelope_cache: bool = True,
    ) -> TaskHandle:
        envelope = replace(
            envelope,
            agent_id=normalize_agent_id(envelope.agent_id),
            session_key=canonicalize_session_key(envelope.session_key),
        )
        queue_mode = mode or "followup"
        if queue_mode == "collect":
            collected = await self._try_collect(
                envelope=envelope,
                message=message,
                run_kind=run_kind,
                no_memory_capture=no_memory_capture,
            )
            if collected is not None:
                return collected
        if queue_mode == "interrupt":
            await self.cancel(session_key=envelope.session_key)
        elif self._max_pending_per_session is not None:
            async with self._state_lock:
                pending_count = len(self._pending_by_session.get(envelope.session_key, []))
            if pending_count >= self._max_pending_per_session:
                _emit_metric(
                    "queue_full_errors_total",
                    value=1,
                    session_key=envelope.session_key,
                )
                raise TaskQueueFullError(
                    session_key=envelope.session_key,
                    max_pending=self._max_pending_per_session,
                )

        record = AgentTaskRecord(
            session_key=envelope.session_key,
            agent_id=envelope.agent_id,
            source_kind=envelope.source_kind.value,
            queue_mode=queue_mode,
            run_kind=run_kind,
            status=AgentTaskStatus.QUEUED,
            details={
                "source_name": envelope.source_name,
                "input_provenance": envelope.input_provenance,
                "no_memory_capture": no_memory_capture,
                "metadata": envelope.metadata,
            },
        )
        await self._storage.create_agent_task(record)
        runtime_task = _RuntimeTask(
            task_id=record.task_id,
            envelope=envelope,
            message=message,
            attachments=list(attachments or []),
            queue_mode=queue_mode,
            run_kind=run_kind,
            no_memory_capture=no_memory_capture,
            ingress_pipeline_steps=tuple(ingress_pipeline_steps or ()),
            semantic_message=semantic_message,
            stream_event_sink=stream_event_sink,
        )
        async with self._state_lock:
            self._tasks[record.task_id] = runtime_task
            self._pending_by_session.setdefault(envelope.session_key, []).append(runtime_task)
            self._scheduler.enroll(runtime_task)
            if update_envelope_cache:
                self._last_envelope_by_session[envelope.session_key] = envelope
            runtime_task.asyncio_task = asyncio.create_task(self._execute(runtime_task))
            _queue_depth = len(self._pending_by_session.get(envelope.session_key, []))
        _emit_metric(
            "opensquilla_queue_depth",
            value=_queue_depth,
            session_key=envelope.session_key,
        )
        await self._emit(envelope.session_key, "task.queued", {"task_id": record.task_id})
        return TaskHandle(
            task_id=record.task_id,
            session_key=envelope.session_key,
            status=AgentTaskStatus.QUEUED,
        )

    async def status(self, task_id: str) -> AgentTaskRecord:
        record = await self._storage.get_agent_task(task_id)
        if record is None:
            raise KeyError(f"Agent task not found: {task_id}")
        return cast(AgentTaskRecord, record)

    async def list(
        self,
        session_key: str | None = None,
        status: str | AgentTaskStatus | None = None,
    ) -> list[AgentTaskRecord]:
        if session_key is not None:
            session_key = canonicalize_session_key(session_key)
        return cast(
            list[AgentTaskRecord],
            await self._storage.list_agent_tasks(session_key=session_key, status=status),
        )

    async def cancel(
        self,
        task_id: str | None = None,
        session_key: str | None = None,
    ) -> int:
        if task_id is None and session_key is None:
            raise ValueError("task_id or session_key is required")
        if session_key is not None:
            session_key = canonicalize_session_key(session_key)
        async with self._state_lock:
            tasks = [
                task
                for task in self._tasks.values()
                if (task_id is None or task.task_id == task_id)
                and (session_key is None or task.envelope.session_key == session_key)
                and task.status not in TERMINAL_STATUSES
            ]
            for task in tasks:
                task.cancel_requested = True
                if task.asyncio_task is not None and not task.asyncio_task.done():
                    task.asyncio_task.cancel()
        return len(tasks)

    async def send(
        self,
        session_key: str,
        message: str,
        provenance: dict[str, Any] | None = None,
        stream_event_sink: TaskStreamEventSink | None = None,
    ) -> TaskHandle:
        session_key = canonicalize_session_key(session_key)
        cached = self._last_envelope_by_session.get(session_key)
        if cached is None:
            envelope = RouteEnvelope(
                source_kind=SourceKind.SYSTEM,
                source_name="task_runtime",
                agent_id=parse_agent_id(session_key),
                session_key=session_key,
                input_provenance=provenance or {"kind": "runtime_send"},
            )
            return await self.enqueue(
                envelope,
                message,
                mode="followup",
                stream_event_sink=stream_event_sink,
            )
        if provenance is None:
            return await self.enqueue(
                cached,
                message,
                mode="followup",
                stream_event_sink=stream_event_sink,
            )
        # Caller-provided provenance is a one-shot override: build an
        # ephemeral envelope from the cached metadata but with this
        # provenance, and skip writing it back to the cache so subsequent
        # ``send(provenance=None)`` calls fall back to the original cached
        # provenance instead of inheriting the override.
        ephemeral = replace(cached, input_provenance=provenance)
        return await self.enqueue(
            ephemeral,
            message,
            mode="followup",
            stream_event_sink=stream_event_sink,
            update_envelope_cache=False,
        )

    async def wait(self, task_id: str, timeout: float | None = None) -> AgentTaskRecord:
        runtime_task = self._tasks.get(task_id)
        if runtime_task is None:
            return await self.status(task_id)
        await asyncio.wait_for(runtime_task.done.wait(), timeout=timeout)
        return await self.status(task_id)

    async def shutdown(
        self,
        *,
        cancel: bool = True,
        timeout: float = 5.0,
        graceful: bool = False,
        graceful_timeout: float | None = None,
    ) -> None:
        """Shut down all in-flight tasks.

        Parameters
        ----------
        cancel:
            When ``True`` (default), cancel all in-flight tasks immediately
            before waiting.  Set to ``False`` for a drain-only wait.
        timeout:
            How long to wait for tasks after cancellation (or without it when
            ``cancel=False``).  Tasks still running after this deadline are
            marked ABANDONED.
        graceful:
            Convenience flag for graceful-drain mode: waits for all in-flight
            tasks to complete naturally before falling back to cancel.  When
            ``True``, ``cancel`` is ignored for the initial wait phase and the
            ``graceful_timeout`` deadline is used.  After the deadline (if any),
            remaining tasks are cancelled with a short ``timeout`` wait.
        graceful_timeout:
            Deadline (seconds) for the graceful drain phase.  ``None`` means
            wait indefinitely (use with care in production; set a finite value).
        """
        tasks = [
            task.asyncio_task
            for task in self._tasks.values()
            if task.asyncio_task is not None and not task.asyncio_task.done()
        ]
        if not tasks:
            return

        if graceful:
            # Phase 1: wait for all tasks to finish naturally.
            try:
                await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True),
                    timeout=graceful_timeout,
                )
                return
            except TimeoutError:
                log.warning(
                    "task_runtime.graceful_shutdown_timeout",
                    graceful_timeout=graceful_timeout,
                    remaining=sum(1 for t in tasks if not t.done()),
                )
            # Phase 2: cancel whatever is still running after the drain timeout.
            tasks = [t for t in tasks if not t.done()]

        if cancel:
            for task in tasks:
                task.cancel()
        if tasks:
            done, pending = await asyncio.wait(tasks, timeout=timeout)
            for task in pending:
                task.cancel()
            if pending:
                await self._mark_unfinished_abandoned()
            for task in done:
                try:
                    task.result()
                except (asyncio.CancelledError, Exception):
                    pass

    async def _try_collect(
        self,
        *,
        envelope: RouteEnvelope,
        message: str,
        run_kind: str,
        no_memory_capture: bool,
    ) -> TaskHandle | None:
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
            details = {
                "source_name": candidate.envelope.source_name,
                "input_provenance": candidate.envelope.input_provenance,
                "metadata": candidate.envelope.metadata,
                "collected": True,
                "message_count": candidate.message.count("\n") + 1,
                "no_memory_capture": candidate.no_memory_capture,
            }
        await self._storage.update_agent_task(candidate.task_id, details=details)
        return TaskHandle(
            task_id=candidate.task_id,
            session_key=envelope.session_key,
            status=AgentTaskStatus.QUEUED,
        )

    async def _execute(self, task: _RuntimeTask) -> None:
        session_key = task.envelope.session_key
        lock = self._session_locks.setdefault(session_key, asyncio.Lock())
        callbacks = TaskRuntimeExecutionCallbacks(
            wait_for_subagent_slot=self._wait_for_subagent_slot,
            acquire_fair_slot=self._acquire_fair_slot,
            release_slot=self._release_slot,
            mark_terminal=self._mark_terminal,
            turn_handler=self._turn_handler,
            emit_metric=_emit_metric,
        )
        await execute_task_lifecycle(task=task, session_lock=lock, callbacks=callbacks)

    async def _acquire_fair_slot(self, task: _RuntimeTask) -> None:
        await self._scheduler.acquire_fair_slot(
            task,
            mark_running=self._mark_running,
            emit_metric=_emit_metric,
        )

    async def _wait_for_subagent_slot(self, task: _RuntimeTask) -> None:
        await self._scheduler.wait_for_subagent_slot(task)

    async def _release_slot(self, task: _RuntimeTask) -> None:
        await self._scheduler.release_slot(task)

    def _get_session_lock_for_turn(self, session_key: str) -> asyncio.Lock:
        """Return the OUTER per-session lock for *session_key*.

        Exposed as a ``session_lock_provider`` callable for ``TurnRunner`` so
        that both classes share the same ``asyncio.Lock`` per session.  After
        Step 7c this becomes the *only* per-session lock; TurnRunner's internal
        ``_session_locks`` dict is removed.

        ``setdefault`` is atomic in CPython — avoids TOCTOU race on insertion.
        """
        return self._session_locks.setdefault(session_key, asyncio.Lock())

    async def _mark_running(self, task: _RuntimeTask) -> None:
        async with self._state_lock:
            task.status = AgentTaskStatus.RUNNING
            self._remove_pending(task)
            self._running_by_session[task.envelope.session_key] = task
        await self._storage.update_agent_task(
            task.task_id,
            status=AgentTaskStatus.RUNNING,
            started_at=_loop_time_ms(),
        )
        await self._emit(task.envelope.session_key, "task.running", {"task_id": task.task_id})

    async def _mark_terminal(
        self,
        task: _RuntimeTask,
        status: AgentTaskStatus,
        *,
        terminal_reason: str,
        error_class: str | None = None,
        error_message: str | None = None,
    ) -> None:
        async with self._state_lock:
            if task.terminal_emitted:
                return
            task.terminal_emitted = True
            task.status = status
            self._remove_pending(task)
            if self._running_by_session.get(task.envelope.session_key) is task:
                self._running_by_session.pop(task.envelope.session_key, None)
            self._tasks.pop(task.task_id, None)
            self._last_envelope_by_session.pop(task.envelope.session_key, None)
            # C3 fix: never pop _session_locks here.  Popping while _execute
            # still holds the lock causes split-brain: a concurrent enqueue
            # calls setdefault() and gets a *new* lock object, allowing two
            # tasks to run concurrently for the same session.  The lock dict
            # grows at most by # unique session_keys (one Lock ~200 B each),
            # which is acceptable.
            session_key = task.envelope.session_key
            # Clean up RR deque entry when session has no more work.
            if (
                not self._pending_by_session.get(session_key)
                and self._running_by_session.get(session_key) is None
            ):
                self._scheduler.remove_inactive_session(task, has_session_work=False)
        await self._storage.update_agent_task(
            task.task_id,
            status=status,
            finished_at=_loop_time_ms(),
            terminal_reason=terminal_reason,
            error_class=error_class,
            error_message=error_message,
        )
        payload = {
            "task_id": task.task_id,
            **build_task_terminal_payload(
                status,
                terminal_reason=terminal_reason,
                error_class=error_class,
                error_message=error_message,
            ),
        }
        await self._emit(task.envelope.session_key, f"task.{status.value}", payload)
        task.done.set()
        await notify_subagent_terminal(
            self._terminal_listener,
            run_kind=task.run_kind,
            parent_session_key=task.envelope.metadata.get("parent_session_key"),
            child_session_key=task.envelope.session_key,
            task_id=task.task_id,
            status=status,
            terminal_reason=terminal_reason,
            agent_id=task.envelope.agent_id,
            parent_task_id=task.envelope.metadata.get("parent_task_id"),
            error_class=error_class,
            error_message=error_message,
        )

    async def _mark_unfinished_abandoned(self) -> None:
        async with self._state_lock:
            unfinished = [
                task for task in self._tasks.values() if task.status not in TERMINAL_STATUSES
            ]
        for task in unfinished:
            await self._mark_terminal(
                task,
                AgentTaskStatus.ABANDONED,
                terminal_reason="shutdown_timeout",
            )

    def _remove_pending(self, task: _RuntimeTask) -> None:
        pending = self._pending_by_session.get(task.envelope.session_key)
        if not pending:
            return
        try:
            pending.remove(task)
        except ValueError:
            return
        if not pending:
            self._pending_by_session.pop(task.envelope.session_key, None)

    async def _emit(self, session_key: str, event_name: str, payload: dict[str, Any]) -> None:
        if self._event_emitter is None:
            return
        await self._event_emitter(session_key, event_name, payload)

def _loop_time_ms() -> int:
    return int(asyncio.get_running_loop().time() * 1000)
