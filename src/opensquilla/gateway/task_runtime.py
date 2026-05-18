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
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any, cast

import structlog

from opensquilla.gateway.routing import RouteEnvelope, SourceKind
from opensquilla.gateway.session_lifecycle import TaskLifecycleEvent, TaskLifecycleListener
from opensquilla.session.keys import canonicalize_session_key, normalize_agent_id, parse_agent_id
from opensquilla.session.models import AgentTaskRecord, AgentTaskStatus
from opensquilla.session.terminal_reply import (
    build_terminal_reply,
    is_context_payload_too_large,
    sanitize_agent_error,
)

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

TaskStreamEventSink = Callable[[Any], Awaitable[None]]


@dataclass(frozen=True)
class TaskHandle:
    task_id: str
    session_key: str
    status: AgentTaskStatus


@dataclass(frozen=True)
class TaskRun:
    task_id: str
    envelope: RouteEnvelope
    message: str
    attachments: list[dict[str, Any]] = field(default_factory=list)
    queue_mode: str = "followup"
    run_kind: str = "default"
    no_memory_capture: bool = False
    # Per-call ingress observability. Lives here, NOT on
    # ``envelope.metadata``, so the cached envelope in
    # ``_last_envelope_by_session`` cannot leak stale ingress markers into
    # later runtime sends (e.g. ``TaskRuntime.send`` reusing the cache).
    ingress_pipeline_steps: tuple[Any, ...] = ()
    # Raw user text used by semantic runtime processing when the runtime path
    # needs to diverge from ``message``. Channels
    # set this to the pre-stamping content; web/CLI leave it ``None`` so
    # ``TurnRunner.run`` falls back to ``message`` as the semantic input.
    semantic_message: str | None = None
    # Optional transcript entry id for the user message already persisted by
    # the ingress surface. Kept off RouteEnvelope.metadata so cached envelopes
    # cannot leak stale one-turn ids into later runtime sends.
    persisted_user_message_id: str | None = None
    # Optional in-process sink for the structured events produced by this
    # specific task's turn stream. Used by channel delivery to mirror the
    # same live text stream that WebUI already receives without changing
    # the public WS event payload.
    stream_event_sink: TaskStreamEventSink | None = None

    @property
    def session_key(self) -> str:
        return self.envelope.session_key

    @property
    def agent_id(self) -> str:
        return self.envelope.agent_id

    @property
    def input_provenance(self) -> dict[str, Any]:
        return self.envelope.input_provenance


@dataclass(frozen=True)
class SubagentCompletionEvent:
    """Terminal event for a runtime-backed subagent task."""

    parent_session_key: str
    child_session_key: str
    task_id: str
    status: AgentTaskStatus
    terminal_reason: str
    agent_id: str | None = None
    parent_task_id: str | None = None
    error_class: str | None = None
    error_message: str | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "type": "subagent_completion",
            "parent_session_key": self.parent_session_key,
            "child_session_key": self.child_session_key,
            "task_id": self.task_id,
            "status": self.status.value,
            "terminal_reason": self.terminal_reason,
        }
        if self.agent_id:
            payload["agent_id"] = self.agent_id
        if self.parent_task_id:
            payload["parent_task_id"] = self.parent_task_id
        if self.error_class:
            payload["error_class"] = self.error_class
        if self.error_message:
            payload["error_message"] = self.error_message
        if self.status != AgentTaskStatus.SUCCEEDED:
            payload["terminal_message"] = build_terminal_reply(payload)
        return payload


@dataclass
class _RuntimeTask:
    task_id: str
    envelope: RouteEnvelope
    message: str
    attachments: list[dict[str, Any]]
    queue_mode: str
    run_kind: str
    no_memory_capture: bool
    status: AgentTaskStatus = AgentTaskStatus.QUEUED
    asyncio_task: asyncio.Task[None] | None = None
    ingress_pipeline_steps: tuple[Any, ...] = ()
    semantic_message: str | None = None
    persisted_user_message_id: str | None = None
    stream_event_sink: TaskStreamEventSink | None = None
    done: asyncio.Event = field(default_factory=asyncio.Event)
    terminal_emitted: bool = False
    cancel_requested: bool = False
    acquired_slot: bool = False
    overflow_dropped: bool = False


TaskHandler = Callable[[TaskRun], Awaitable[Any]]
EventEmitter = Callable[[str, str, dict[str, Any]], Awaitable[None]]
TerminalListener = Callable[[SubagentCompletionEvent], Awaitable[None]]


class PendingOverflowPolicy(StrEnum):
    """Per-session pending queue overflow policy.

    ``REJECT_NEWEST``
        Default — refuse the new enqueue with ``TaskQueueFullError``.
        Backwards compatible behaviour.

    ``DROP_OLDEST``
        Evict the oldest QUEUED pending task on the same session, mark it
        ``CANCELLED`` with ``terminal_reason="dropped_by_overflow"``, and
        accept the new enqueue. Running tasks are never evicted.
    """

    REJECT_NEWEST = "reject_newest"
    DROP_OLDEST = "drop_oldest"


class TaskQueueFullError(RuntimeError):
    """Raised when a session's waiting queue reaches its configured limit."""

    def __init__(self, *, session_key: str, max_pending: int) -> None:
        super().__init__(
            f"task queue overflow for session '{session_key}': "
            f"max_pending_per_session={max_pending}"
        )
        self.session_key = session_key
        self.max_pending = max_pending


class _TurnHardDeadlineExceeded(TimeoutError):  # noqa: N818
    """Internal breaker error raised when a turn exceeds its hard deadline.

    Subclasses TimeoutError so legacy ``except TimeoutError`` paths still
    classify the run as timed out, but the dedicated type lets the runtime
    annotate the terminal record with the breaker-specific reason.
    """

    def __init__(self, *, deadline_s: float) -> None:
        super().__init__(
            f"turn exceeded hard deadline of {deadline_s:g}s"
        )
        self.deadline_s = deadline_s


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
        lifecycle_listener: TaskLifecycleListener | None = None,
        max_concurrency: int = 4,
        max_pending_per_session: int | None = 64,
        subagent_reserved_slots: int = 0,
        turn_hard_deadline_s: float | None = None,
        pending_overflow_policy: PendingOverflowPolicy | str = (
            PendingOverflowPolicy.REJECT_NEWEST
        ),
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be >= 1")
        if max_pending_per_session is not None and max_pending_per_session < 1:
            raise ValueError("max_pending_per_session must be >= 1")
        if subagent_reserved_slots < 0:
            raise ValueError("subagent_reserved_slots must be >= 0")
        if turn_hard_deadline_s is not None and turn_hard_deadline_s <= 0:
            raise ValueError("turn_hard_deadline_s must be > 0 or None")
        try:
            pending_overflow_policy = PendingOverflowPolicy(pending_overflow_policy)
        except ValueError as exc:
            valid = ", ".join(member.value for member in PendingOverflowPolicy)
            raise ValueError(
                f"pending_overflow_policy must be one of {{{valid}}}"
            ) from exc
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
        self._lifecycle_listener = lifecycle_listener
        self._max_pending_per_session = max_pending_per_session
        self._max_concurrency = max_concurrency
        self._subagent_reserved_slots = subagent_reserved_slots
        self._turn_hard_deadline_s = turn_hard_deadline_s
        self._pending_overflow_policy = pending_overflow_policy
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
        # In-flight counters track tasks that have actually acquired a slot.
        # They drive the reserved-slot fairness gate for subagent runs.
        self._global_in_flight = 0
        self._subagent_in_flight = 0
        # Lazily constructed so the runtime can be instantiated outside an
        # event loop (some tests do this); the Condition is bound to the
        # running loop the first time a subagent waits on a slot.
        self._slot_cond: asyncio.Condition | None = None
        # Per-agent-id fair-queuing state (true round-robin).
        #
        # Design: true round-robin across sessions of the same agent_id.
        # ``_agent_session_rr[agent_id]`` is a deque of session_keys that have
        # active (pending or running) tasks for that agent.  When a task needs a
        # slot it must be at the front of its agent's deque; after acquiring the
        # slot the deque entry rotates to the tail so the next session goes next.
        # When a session has no more pending/running tasks it is removed from the
        # deque in ``_mark_terminal``.
        #
        # ``_agent_active_sessions[agent_id]`` tracks the set of session_keys
        # that currently have at least one pending or running task.  It is the
        # membership oracle that ``_mark_terminal`` uses to decide whether to
        # evict a session_key from the deque.
        #
        # The global slot cap (``_global_in_flight < _max_concurrency``) is
        # enforced as before.  Per-agent RR is the fairness layer inside that cap.
        #
        # Lazily initialised like _slot_cond.
        self._agent_session_rr: dict[str, deque[str]] = {}
        self._agent_active_sessions: dict[str, set[str]] = {}
        self._agent_in_flight: dict[str, int] = {}
        self._fair_cond: asyncio.Condition | None = None

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
        persisted_user_message_id: str | None = None,
        stream_event_sink: TaskStreamEventSink | None = None,
        *,
        update_envelope_cache: bool = True,
        overflow_policy: PendingOverflowPolicy | str | None = None,
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
            effective_policy = self._pending_overflow_policy
            if overflow_policy is not None:
                try:
                    effective_policy = PendingOverflowPolicy(overflow_policy)
                except ValueError as exc:
                    valid = ", ".join(member.value for member in PendingOverflowPolicy)
                    raise ValueError(
                        f"overflow_policy must be one of {{{valid}}}"
                    ) from exc
            await self._apply_overflow_policy(
                envelope.session_key,
                policy=effective_policy,
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
                "persisted_user_message_id": persisted_user_message_id,
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
            persisted_user_message_id=persisted_user_message_id,
            stream_event_sink=stream_event_sink,
        )
        async with self._state_lock:
            self._tasks[record.task_id] = runtime_task
            self._pending_by_session.setdefault(envelope.session_key, []).append(runtime_task)
            # Register session in per-agent RR deque (if not already).
            agent_id = envelope.agent_id
            session_key = envelope.session_key
            if agent_id not in self._agent_session_rr:
                self._agent_session_rr[agent_id] = deque()
                self._agent_active_sessions[agent_id] = set()
            active = self._agent_active_sessions[agent_id]
            rr = self._agent_session_rr[agent_id]
            if session_key not in active:
                active.add(session_key)
                rr.append(session_key)
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

    async def apply_overflow_policy(
        self,
        session_key: str,
        *,
        policy: PendingOverflowPolicy | str | None = None,
    ) -> None:
        """Public entry point for per-channel overflow enforcement.

        Channel adapters call this before issuing the per-session
        ``start_turn_via_runtime`` so they can override the runtime default
        (e.g. ``DROP_OLDEST`` for noisy realtime channels). When ``policy``
        is ``None`` the runtime's own default is used.
        """
        if self._max_pending_per_session is None:
            return
        resolved: PendingOverflowPolicy | None = None
        if policy is not None:
            try:
                resolved = PendingOverflowPolicy(policy)
            except ValueError as exc:
                valid = ", ".join(member.value for member in PendingOverflowPolicy)
                raise ValueError(
                    f"overflow_policy must be one of {{{valid}}}"
                ) from exc
        await self._apply_overflow_policy(
            canonicalize_session_key(session_key),
            policy=resolved,
        )

    async def _apply_overflow_policy(
        self,
        session_key: str,
        *,
        policy: PendingOverflowPolicy | None = None,
    ) -> None:
        """Enforce ``max_pending_per_session`` per the resolved policy.

        ``policy`` overrides the runtime default for this single call so a
        channel adapter may pick its own behaviour (e.g. ``DROP_OLDEST`` for
        noisy realtime channels).

        Holds ``_state_lock`` only while inspecting/snapshotting pending state
        and (for ``drop_oldest``) selecting the eviction candidate. The
        cancellation work itself runs outside the lock so ``_mark_terminal``
        can re-acquire ``_state_lock`` safely.
        """
        assert self._max_pending_per_session is not None
        if policy is None:
            policy = self._pending_overflow_policy
        async with self._state_lock:
            pending = list(self._pending_by_session.get(session_key, []))
            pending_count = len(pending)
            victim: _RuntimeTask | None = None
            if pending_count >= self._max_pending_per_session:
                if policy == PendingOverflowPolicy.DROP_OLDEST:
                    victim = next(
                        (
                            task
                            for task in pending
                            if task.status == AgentTaskStatus.QUEUED
                        ),
                        None,
                    )
                if policy != PendingOverflowPolicy.DROP_OLDEST or victim is None:
                    _emit_metric(
                        "queue_full_errors_total",
                        value=1,
                        session_key=session_key,
                        policy=str(policy),
                    )
                    raise TaskQueueFullError(
                        session_key=session_key,
                        max_pending=self._max_pending_per_session,
                    )
                # Mark before releasing the lock so a concurrent enqueue
                # cannot pick the same victim and double-cancel.
                victim.cancel_requested = True
                victim.overflow_dropped = True
        if victim is not None:
            _emit_metric(
                "queue_full_errors_total",
                value=1,
                session_key=session_key,
                policy=str(PendingOverflowPolicy.DROP_OLDEST),
                action="dropped_oldest",
            )
            # Cancel the asyncio task driving _execute(). The asyncio.Lock
            # acquire path may swallow the cancel via a race when the lock
            # holder releases at the same instant, so we always finalise
            # the record ourselves: _mark_terminal is idempotent (guarded
            # by terminal_emitted) so a redundant call from the _execute
            # cancel branch is a no-op.
            asyncio_task = victim.asyncio_task
            if asyncio_task is not None and not asyncio_task.done():
                asyncio_task.cancel()
            await self._mark_terminal(
                victim,
                AgentTaskStatus.CANCELLED,
                terminal_reason="dropped_by_overflow",
            )

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
        try:
            async with lock:
                # Signal to TurnRunner.run() that this Task already holds the
                # session lock so run() can skip re-acquisition without using
                # lock.locked() (which cannot distinguish owners across tasks).
                from opensquilla.engine.runtime import _SESSION_LOCK_OWNER

                _current_task = asyncio.current_task()
                _prev_map = _SESSION_LOCK_OWNER.get(None)
                _new_map: dict[int, Any] = dict(_prev_map or {})
                if _current_task is not None:
                    _new_map[id(lock)] = _current_task
                _owner_token = _SESSION_LOCK_OWNER.set(_new_map)
                try:
                    if task.cancel_requested:
                        reason = (
                            "overflow_drop" if task.overflow_dropped else "user_cancel"
                        )
                        terminal_reason = (
                            "dropped_by_overflow"
                            if task.overflow_dropped
                            else "cancelled_before_start"
                        )
                        _emit_metric(
                            "turn_cancellations_total",
                            value=1,
                            reason=reason,
                            session_key=task.envelope.session_key,
                        )
                        await self._mark_terminal(
                            task,
                            AgentTaskStatus.CANCELLED,
                            terminal_reason=terminal_reason,
                        )
                        return
                    await self._wait_for_subagent_slot(task)
                    acquired = False
                    try:
                        await self._acquire_fair_slot(task)
                        acquired = True
                        run = TaskRun(
                            task_id=task.task_id,
                            envelope=task.envelope,
                            message=task.message,
                            attachments=task.attachments,
                            queue_mode=task.queue_mode,
                            run_kind=task.run_kind,
                            no_memory_capture=task.no_memory_capture,
                            ingress_pipeline_steps=task.ingress_pipeline_steps,
                            semantic_message=task.semantic_message,
                            persisted_user_message_id=task.persisted_user_message_id,
                            stream_event_sink=task.stream_event_sink,
                        )
                        if self._turn_hard_deadline_s is not None:
                            _deadline_start = time.monotonic()
                            try:
                                await asyncio.wait_for(
                                    self._turn_handler(run),
                                    timeout=self._turn_hard_deadline_s,
                                )
                            except TimeoutError as exc:
                                # Only reclassify when the hard-deadline budget
                                # was actually exhausted.  A TimeoutError that
                                # originates inside the handler (e.g. from a
                                # stage class or tool call) will have elapsed
                                # well below the deadline; in that case re-raise
                                # the original exception unchanged so the outer
                                # handler records the correct cause.
                                _elapsed = time.monotonic() - _deadline_start
                                if _elapsed + 0.01 >= self._turn_hard_deadline_s:
                                    raise _TurnHardDeadlineExceeded(
                                        deadline_s=self._turn_hard_deadline_s,
                                    ) from exc
                                raise
                        else:
                            await self._turn_handler(run)
                        await self._mark_terminal(
                            task,
                            AgentTaskStatus.SUCCEEDED,
                            terminal_reason="completed",
                        )
                    finally:
                        if acquired:
                            await self._release_slot(task)
                finally:
                    _SESSION_LOCK_OWNER.reset(_owner_token)
        except asyncio.CancelledError:
            reason = "overflow_drop" if task.overflow_dropped else "interrupt"
            terminal_reason = (
                "dropped_by_overflow" if task.overflow_dropped else "cancelled"
            )
            _emit_metric(
                "turn_cancellations_total",
                value=1,
                reason=reason,
                session_key=task.envelope.session_key,
            )
            await self._mark_terminal(
                task,
                AgentTaskStatus.CANCELLED,
                terminal_reason=terminal_reason,
            )
        except _TurnHardDeadlineExceeded as exc:
            _emit_metric(
                "turn_cancellations_total",
                value=1,
                reason="hard_deadline",
                session_key=task.envelope.session_key,
            )
            await self._mark_terminal(
                task,
                AgentTaskStatus.TIMEOUT,
                terminal_reason="hard_deadline_exceeded",
                error_class=type(exc).__name__,
                error_message=str(exc),
            )
        except TimeoutError as exc:
            _emit_metric(
                "turn_cancellations_total",
                value=1,
                reason="timeout",
                session_key=task.envelope.session_key,
            )
            await self._mark_terminal(
                task,
                AgentTaskStatus.TIMEOUT,
                terminal_reason="timeout",
                error_class=type(exc).__name__,
                error_message=str(exc),
            )
        except Exception as exc:  # noqa: BLE001 - runtime ledger records the class.
            terminal_reason = str(getattr(exc, "terminal_reason", None) or "error")
            status = (
                AgentTaskStatus.TIMEOUT
                if terminal_reason == "timeout"
                else AgentTaskStatus.FAILED
            )
            await self._mark_terminal(
                task,
                status,
                terminal_reason=terminal_reason,
                error_class=str(getattr(exc, "code", None) or type(exc).__name__),
                error_message=str(exc),
            )

    def _ensure_slot_cond(self) -> asyncio.Condition:
        if self._slot_cond is None:
            self._slot_cond = asyncio.Condition()
        return self._slot_cond

    def _ensure_fair_cond(self) -> asyncio.Condition:
        if self._fair_cond is None:
            self._fair_cond = asyncio.Condition()
        return self._fair_cond

    async def _acquire_fair_slot(self, task: _RuntimeTask) -> None:
        """Acquire one global concurrency slot with per-agent_id round-robin enrollment.

        A task must satisfy one predicate before it is granted a slot:

        1. A slot is available: ``_global_in_flight < _max_concurrency``.

        The per-agent RR deque is rotated on each acquire so that the *next*
        task to grab a free slot comes from the next session in enrollment
        order.  Crucially, the deque is NOT used as a blocking gate — it only
        controls which session goes first when multiple sessions are competing
        for the same slot.  This means sessions of the same agent with
        different session_keys can all run concurrently when idle slots exist,
        preventing head-session blocking.

        When only one slot is left (``_global_in_flight == _max_concurrency - 1``),
        the session at the front of the agent's RR deque is preferred: other
        sessions of the same agent yield so the deque head gets the last slot.
        This preserves starvation-free round-robin ordering without blocking
        concurrent execution when multiple slots are free.

        When a slot is released ``_fair_cond.notify_all()`` wakes all waiters
        so they re-check the predicate.
        """
        cond = self._ensure_fair_cond()
        agent_id = task.envelope.agent_id
        session_key = task.envelope.session_key

        async with cond:
            while True:
                # Predicate 1: global slot available.
                if self._global_in_flight >= self._max_concurrency:
                    await cond.wait()
                    continue
                # Tie-break: when exactly one slot remains and this agent has
                # multiple active sessions, only the deque-head session may
                # take it.  All other sessions of this agent yield so that RR
                # ordering is preserved without wasting the slot.
                idle_slots = self._max_concurrency - self._global_in_flight
                rr = self._agent_session_rr.get(agent_id)
                if idle_slots == 1 and rr and len(rr) > 1 and rr[0] != session_key:
                    await cond.wait()
                    continue
                # Predicate satisfied — rotate deque and claim the slot.
                if rr and rr[0] == session_key:
                    rr.rotate(-1)
                self._global_in_flight += 1
                if task.run_kind == "subagent":
                    self._subagent_in_flight += 1
                self._agent_in_flight[agent_id] = self._agent_in_flight.get(agent_id, 0) + 1
                task.acquired_slot = True
                break

        # Update storage and emit running metric outside the condition lock.
        await self._mark_running(task)
        _emit_metric(
            "in_flight_turns_total",
            value=1,
            session_key=task.envelope.session_key,
        )

    async def _wait_for_subagent_slot(self, task: _RuntimeTask) -> None:
        """Block subagent tasks until at least ``reserved_slots+1`` capacity
        is free, so non-subagent tasks always have a fair runway.
        """
        if task.run_kind != "subagent" or self._subagent_reserved_slots <= 0:
            return
        cond = self._ensure_slot_cond()
        async with cond:
            while (
                self._max_concurrency - self._global_in_flight
                <= self._subagent_reserved_slots
            ):
                await cond.wait()

    async def _release_slot(self, task: _RuntimeTask) -> None:
        async with self._state_lock:
            if task.acquired_slot:
                self._global_in_flight = max(0, self._global_in_flight - 1)
                if task.run_kind == "subagent":
                    self._subagent_in_flight = max(0, self._subagent_in_flight - 1)
                agent_id = task.envelope.agent_id
                new_count = max(0, self._agent_in_flight.get(agent_id, 0) - 1)
                if new_count == 0:
                    self._agent_in_flight.pop(agent_id, None)
                else:
                    self._agent_in_flight[agent_id] = new_count
                task.acquired_slot = False
        # Wake all tasks waiting for a slot: both the subagent-reserved gate
        # (_slot_cond) and the fair-queuing gate (_fair_cond).
        if self._slot_cond is not None:
            async with self._slot_cond:
                self._slot_cond.notify_all()
        if self._fair_cond is not None:
            async with self._fair_cond:
                self._fair_cond.notify_all()

    def _get_session_lock_for_turn(self, session_key: str) -> asyncio.Lock:
        """Return the OUTER per-session lock for *session_key*.

        Exposed as a ``session_lock_provider`` callable for ``TurnRunner`` so
        that both classes share the same ``asyncio.Lock`` per session. With a
        shared provider this is the only per-session lock; TurnRunner no
        longer owns an internal ``_session_locks`` dict.

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
        await self._notify_task_lifecycle(
            TaskLifecycleEvent(
                phase="running",
                session_key=task.envelope.session_key,
                task_id=task.task_id,
                task_status=AgentTaskStatus.RUNNING,
                run_kind=task.run_kind,
            )
        )

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
                agent_id = task.envelope.agent_id
                active = self._agent_active_sessions.get(agent_id)
                if active is not None:
                    active.discard(session_key)
                    rr = self._agent_session_rr.get(agent_id)
                    if rr is not None:
                        try:
                            rr.remove(session_key)
                        except ValueError:
                            pass
                    # Clean up empty agent structures.
                    if not active:
                        self._agent_active_sessions.pop(agent_id, None)
                        self._agent_session_rr.pop(agent_id, None)
        terminal_payload = {
            "status": status,
            "terminal_reason": terminal_reason,
            "error_class": error_class,
            "error_message": error_message,
        }
        if is_context_payload_too_large(terminal_payload):
            error_class, error_message = sanitize_agent_error(
                terminal_payload,
                fallback_error_class=error_class,
                fallback_error_message=error_message or "Agent error",
            )
            terminal_payload["error_class"] = error_class
            terminal_payload["error_message"] = error_message
        await self._storage.update_agent_task(
            task.task_id,
            status=status,
            finished_at=_loop_time_ms(),
            terminal_reason=terminal_reason,
            error_class=error_class,
            error_message=error_message,
            **await self._terminal_details_update(task),
        )
        payload: dict[str, Any] = {
            "task_id": task.task_id,
            "terminal_reason": terminal_reason,
        }
        if status != AgentTaskStatus.SUCCEEDED:
            payload["terminal_message"] = build_terminal_reply(terminal_payload)
        await self._emit(task.envelope.session_key, f"task.{status.value}", payload)
        await self._notify_task_lifecycle(
            TaskLifecycleEvent(
                phase="terminal",
                session_key=task.envelope.session_key,
                task_id=task.task_id,
                task_status=status,
                run_kind=task.run_kind,
                terminal_reason=terminal_reason,
                error_class=error_class,
                error_message=error_message,
            )
        )
        task.done.set()
        await self._notify_subagent_terminal(
            task,
            status,
            terminal_reason=terminal_reason,
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

    async def _notify_task_lifecycle(self, event: TaskLifecycleEvent) -> None:
        if self._lifecycle_listener is None:
            return
        try:
            await self._lifecycle_listener(event)
        except Exception:
            log.warning(
                "task_runtime.lifecycle_listener_failed",
                session_key=event.session_key,
                task_id=event.task_id,
                phase=event.phase,
                task_status=event.task_status,
                exc_info=True,
            )

    async def _notify_subagent_terminal(
        self,
        task: _RuntimeTask,
        status: AgentTaskStatus,
        *,
        terminal_reason: str,
        error_class: str | None = None,
        error_message: str | None = None,
    ) -> None:
        if self._terminal_listener is None or task.run_kind != "subagent":
            return
        parent_session_key = task.envelope.metadata.get("parent_session_key")
        if not isinstance(parent_session_key, str) or not parent_session_key:
            return
        event = SubagentCompletionEvent(
            parent_session_key=parent_session_key,
            child_session_key=task.envelope.session_key,
            task_id=task.task_id,
            status=status,
            terminal_reason=terminal_reason,
            agent_id=task.envelope.agent_id,
            parent_task_id=task.envelope.metadata.get("parent_task_id"),
            error_class=error_class,
            error_message=error_message,
        )
        try:
            await self._terminal_listener(event)
        except Exception:
            return

    async def _terminal_details_update(self, task: _RuntimeTask) -> dict[str, Any]:
        outcome = _subagent_group_outcome_from_provenance(task.envelope.input_provenance)
        if outcome is None:
            return {}
        existing = await self._storage.get_agent_task(task.task_id)
        current_details = getattr(existing, "details", None)
        details = dict(current_details) if isinstance(current_details, dict) else {}
        details["subagent_group_outcome"] = outcome
        disclosure_required = task.envelope.input_provenance.get(
            "runtime_partial_failure_disclosure_required"
        )
        if disclosure_required is True:
            details["runtime_partial_failure_disclosure_required"] = True
        return {"details": details}


def _subagent_group_outcome_from_provenance(
    input_provenance: dict[str, Any],
) -> dict[str, Any] | None:
    if not isinstance(input_provenance, dict):
        return None
    outcome = input_provenance.get("subagent_group_outcome")
    if not isinstance(outcome, dict):
        return None
    return dict(outcome)


def _loop_time_ms() -> int:
    return int(asyncio.get_running_loop().time() * 1000)
