"""In-process task runtime for agent turns.

Lock ordering invariant:
    TaskRuntime owns two per-session lock classes used by gateway-dispatched turns.
    Gateway construction injects ``TaskRuntime._get_session_lock_for_turn`` as
    TurnRunner's ``session_lock_provider``. That provider returns the short
    write lock for transcript/session state mutation.

    ``TaskRuntime._execute()`` acquires a separate execution lock before
    calling the turn handler. ``TurnRunner.run()`` detects that TaskRuntime is
    already serializing the turn lifecycle and skips the old coarse acquire;
    TurnRunner append adapters still acquire the short write lock.

    CLI or standalone TurnRunner instances may use a different provider, but
    they are not nested inside TaskRuntime execution. Keep external I/O outside
    the short write lock.
"""

from __future__ import annotations

import asyncio
import builtins
import contextlib
import time
import uuid
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any, TypeVar, cast

import structlog

from opensquilla.engine.outcome import completed_outcome, outcome_from_error
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
_CollectResult = TypeVar("_CollectResult")


@dataclass(frozen=True)
class TaskHandle:
    task_id: str
    session_key: str
    status: AgentTaskStatus


@dataclass
class TaskReservation:
    """Reversible in-memory admission held until durable acceptance commits."""

    reservation_id: str
    task_record: AgentTaskRecord
    runtime_task: _RuntimeTask
    overflow_victim: _RuntimeTask | None = None
    update_envelope_cache: bool = True
    activated: bool = False
    aborted: bool = False

    @property
    def task_id(self) -> str:
        return self.task_record.task_id

    @property
    def session_key(self) -> str:
        return self.task_record.session_key

    @property
    def status(self) -> AgentTaskStatus:
        return self.task_record.status


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
    # Every persisted user entry folded into this run, in transcript order.
    # ``persisted_user_message_id`` remains the earliest id and therefore the
    # history boundary; this collection is used for multi-message cleanup when
    # the provider rejects the request before a turn can start.
    persisted_user_message_ids: tuple[str, ...] = ()
    # True when the ingress surface observed an empty user transcript before
    # persisting this turn's user message.
    fresh_user_session: bool = False
    # Optional in-process sink for the structured events produced by this
    # specific task's turn stream. Used by channel delivery to mirror the
    # same live text stream that WebUI already receives without changing
    # the public WS event payload.
    stream_event_sink: TaskStreamEventSink | None = None
    # Synchronous finalizer callback carrying the exact assistant transcript
    # row and content produced by this turn. Channel tasks persist it for
    # durable delivery after terminal commit; other run kinds leave it unset.
    assistant_message_sink: Callable[[str | None, str], None] | None = None

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
    persisted_user_message_ids: list[str] = field(default_factory=list)
    message_count: int = 1
    fresh_user_session: bool = False
    terminal_assistant_message_id: str | None = None
    terminal_assistant_message_content: str | None = None
    stream_event_sink: TaskStreamEventSink | None = None
    done: asyncio.Event = field(default_factory=asyncio.Event)
    terminal_emitted: bool = False
    cancel_requested: bool = False
    acquired_slot: bool = False
    overflow_dropped: bool = False
    cancel_source: str | None = None
    cancel_reason: str | None = None
    # Serializes collect persistence/application with this task's running and
    # terminal transitions. It is intentionally per-task: a slow SQLite write
    # for one session must never hold the runtime-wide state lock.
    collect_claim: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    def capture_terminal_assistant_message(
        self,
        message_id: str | None,
        content: str,
    ) -> None:
        self.terminal_assistant_message_id = message_id
        self.terminal_assistant_message_content = content


TaskHandler = Callable[[TaskRun], Awaitable[Any]]
EventEmitter = Callable[[str, str, dict[str, Any]], Awaitable[None]]
TerminalListener = Callable[[SubagentCompletionEvent], Awaitable[None]]


def _ordered_message_ids(
    primary: str | None,
    message_ids: Iterable[str] | None = None,
) -> list[str]:
    """Return stable, non-empty, de-duplicated persisted message ids."""

    ordered: list[str] = []
    for value in (primary, *(message_ids or ())):
        if isinstance(value, str) and value and value not in ordered:
            ordered.append(value)
    return ordered


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


def _clean_cancel_detail(value: str | None, default: str) -> str:
    text = str(value or "").strip()
    if not text:
        return default
    safe = "".join(
        ch if ch.isalnum() or ch in {"_", "-", ".", ":"} else "_"
        for ch in text
    )
    return (safe.strip("_") or default)[:80]


class TaskRuntime:
    """Serialize same-session turns while allowing cross-session concurrency.

    Gateway lock invariant:
        ``self._session_execution_locks`` serializes task execution for a
        session. ``self._session_locks`` stores the short critical-section
        locks shared with TurnRunner and RPC ingress through
        ``_get_session_lock_for_turn``.

        The write lock serializes transcript/session mutations; it must not
        cover model streaming, tool execution, slot waits, or approval waits.
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
        running_heartbeat_interval_s: float | None = 30.0,
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
        if running_heartbeat_interval_s is not None and running_heartbeat_interval_s <= 0:
            raise ValueError("running_heartbeat_interval_s must be > 0 or None")
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
        self._running_heartbeat_interval_s = running_heartbeat_interval_s
        self._pending_overflow_policy = pending_overflow_policy
        # Per-session write locks shared with TurnRunner and RPC ingress on
        # gateway-dispatched turns. These guard short transcript/session state
        # mutations only.
        self._session_locks: dict[str, asyncio.Lock] = {}
        # Per-session execution locks serialize whole turn lifecycles without
        # blocking transcript writes, browser queue acknowledgements, or approval
        # status updates behind external I/O.
        self._session_execution_locks: dict[str, asyncio.Lock] = {}
        self._tasks: dict[str, _RuntimeTask] = {}
        self._pending_by_session: dict[str, list[_RuntimeTask]] = {}
        self._running_by_session: dict[str, _RuntimeTask] = {}
        self._reservations_by_session: dict[str, list[TaskReservation]] = {}
        self._reserved_overflow_victims: set[str] = set()
        self._last_envelope_by_session: dict[str, RouteEnvelope] = {}
        self._state_lock = asyncio.Lock()
        # Admission is per session so durable RPC ingress crosses reserve,
        # commit, and activation in order. This prevents resets from overtaking
        # committed-but-inert reservations; collect also uses the same gate so
        # two sends cannot both miss a candidate and create separate tasks. The
        # lower-level try_collect_atomically deliberately does not re-enter it.
        self._collect_admission_locks: dict[str, asyncio.Lock] = {}
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
        attachments: builtins.list[dict[str, Any]] | None = None,
        mode: str | None = None,
        run_kind: str = "default",
        no_memory_capture: bool = False,
        ingress_pipeline_steps: tuple[Any, ...] | list[Any] | None = None,
        semantic_message: str | None = None,
        persisted_user_message_id: str | None = None,
        persisted_user_message_ids: builtins.list[str] | tuple[str, ...] | None = None,
        message_count: int = 1,
        fresh_user_session: bool = False,
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
            async with self.collect_admission(envelope.session_key):
                collected = await self._try_collect(
                    envelope=envelope,
                    message=message,
                    attachments=attachments,
                    run_kind=run_kind,
                    no_memory_capture=no_memory_capture,
                    semantic_message=semantic_message,
                    persisted_user_message_id=persisted_user_message_id,
                    persisted_user_message_ids=persisted_user_message_ids,
                    message_count=message_count,
                )
                if collected is not None:
                    return collected
                return await self._reserve_persist_and_activate(
                    envelope,
                    message,
                    attachments=attachments,
                    mode=queue_mode,
                    run_kind=run_kind,
                    no_memory_capture=no_memory_capture,
                    ingress_pipeline_steps=ingress_pipeline_steps,
                    semantic_message=semantic_message,
                    persisted_user_message_id=persisted_user_message_id,
                    persisted_user_message_ids=persisted_user_message_ids,
                    message_count=message_count,
                    fresh_user_session=fresh_user_session,
                    stream_event_sink=stream_event_sink,
                    update_envelope_cache=update_envelope_cache,
                    overflow_policy=overflow_policy,
                )
        return await self._reserve_persist_and_activate(
            envelope,
            message,
            attachments=attachments,
            mode=queue_mode,
            run_kind=run_kind,
            no_memory_capture=no_memory_capture,
            ingress_pipeline_steps=ingress_pipeline_steps,
            semantic_message=semantic_message,
            persisted_user_message_id=persisted_user_message_id,
            persisted_user_message_ids=persisted_user_message_ids,
            message_count=message_count,
            fresh_user_session=fresh_user_session,
            stream_event_sink=stream_event_sink,
            update_envelope_cache=update_envelope_cache,
            overflow_policy=overflow_policy,
        )

    @contextlib.asynccontextmanager
    async def collect_admission(self, session_key: str) -> AsyncIterator[None]:
        """Serialize one session's durable ingress and collect decisions.

        Callers that own durable ingress hold this around reserve -> commit ->
        activate for every queue mode. Collect callers also keep it around
        ``try_collect_atomically`` so a miss and the following reservation are
        one admission decision. The lower-level helper does not acquire the gate
        because ``asyncio.Lock`` is not re-entrant.
        """

        key = canonicalize_session_key(session_key)
        lock = self._collect_admission_locks.setdefault(key, asyncio.Lock())
        async with lock:
            yield

    async def _reserve_persist_and_activate(
        self,
        envelope: RouteEnvelope,
        message: str,
        attachments: builtins.list[dict[str, Any]] | None = None,
        mode: str | None = None,
        run_kind: str = "default",
        no_memory_capture: bool = False,
        ingress_pipeline_steps: tuple[Any, ...] | list[Any] | None = None,
        semantic_message: str | None = None,
        persisted_user_message_id: str | None = None,
        persisted_user_message_ids: builtins.list[str] | tuple[str, ...] | None = None,
        message_count: int = 1,
        fresh_user_session: bool = False,
        stream_event_sink: TaskStreamEventSink | None = None,
        *,
        update_envelope_cache: bool = True,
        overflow_policy: PendingOverflowPolicy | str | None = None,
    ) -> TaskHandle:
        """Persist and activate one direct enqueue without cancellation drift."""

        reservation = await self.reserve(
            envelope,
            message,
            attachments=attachments,
            mode=mode,
            run_kind=run_kind,
            no_memory_capture=no_memory_capture,
            ingress_pipeline_steps=ingress_pipeline_steps,
            semantic_message=semantic_message,
            persisted_user_message_id=persisted_user_message_id,
            persisted_user_message_ids=persisted_user_message_ids,
            message_count=message_count,
            fresh_user_session=fresh_user_session,
            stream_event_sink=stream_event_sink,
            update_envelope_cache=update_envelope_cache,
            overflow_policy=overflow_policy,
        )
        try:
            await self._storage.create_agent_task(reservation.task_record)
        except asyncio.CancelledError:
            # The shared storage layer may finish COMMIT after its caller is
            # cancelled. Settle the operation, read back by task_id, and cross
            # exactly one in-memory boundary: persisted tasks activate; absent
            # tasks release their inert reservation.
            persisted = await self._wait_for_task_settlement(
                asyncio.create_task(self._storage.get_agent_task(reservation.task_id))
            )
            if persisted is None:
                await self._wait_for_task_settlement(
                    asyncio.create_task(self.abort_reservation(reservation))
                )
            else:
                await self._wait_for_task_settlement(
                    asyncio.create_task(self.activate(reservation))
                )
            raise
        except BaseException:
            await self.abort_reservation(reservation)
            raise
        try:
            return await self.activate(reservation)
        except asyncio.CancelledError:
            # Persistence has definitely returned successfully. If cancellation
            # arrived before ``activate`` crossed its in-memory boundary, finish
            # activation in a fresh child; otherwise the reservation already owns
            # the live task and only the caller cancellation remains to propagate.
            if not reservation.activated:
                await self._wait_for_task_settlement(
                    asyncio.create_task(self.activate(reservation))
                )
            raise

    @staticmethod
    async def _wait_for_task_settlement[T](task: asyncio.Task[T]) -> T:
        """Wait for a child operation without forwarding caller cancellation."""

        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
        return task.result()

    async def reserve(
        self,
        envelope: RouteEnvelope,
        message: str,
        attachments: builtins.list[dict[str, Any]] | None = None,
        mode: str | None = None,
        run_kind: str = "default",
        no_memory_capture: bool = False,
        ingress_pipeline_steps: tuple[Any, ...] | list[Any] | None = None,
        semantic_message: str | None = None,
        persisted_user_message_id: str | None = None,
        persisted_user_message_ids: builtins.list[str] | tuple[str, ...] | None = None,
        message_count: int = 1,
        fresh_user_session: bool = False,
        stream_event_sink: TaskStreamEventSink | None = None,
        *,
        update_envelope_cache: bool = True,
        overflow_policy: PendingOverflowPolicy | str | None = None,
    ) -> TaskReservation:
        """Reserve queue admission without persistence, cancellation, or execution."""

        envelope = replace(
            envelope,
            agent_id=normalize_agent_id(envelope.agent_id),
            session_key=canonicalize_session_key(envelope.session_key),
        )
        queue_mode = mode or "followup"
        normalized_message_ids = _ordered_message_ids(
            persisted_user_message_id,
            persisted_user_message_ids,
        )
        persisted_user_message_id = (
            normalized_message_ids[0] if normalized_message_ids else None
        )
        message_count = max(1, int(message_count))
        effective_policy = self._pending_overflow_policy
        if overflow_policy is not None:
            try:
                effective_policy = PendingOverflowPolicy(overflow_policy)
            except ValueError as exc:
                valid = ", ".join(member.value for member in PendingOverflowPolicy)
                raise ValueError(
                    f"overflow_policy must be one of {{{valid}}}"
                ) from exc

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
                "persisted_user_message_ids": normalized_message_ids,
                "message_count": message_count,
                "fresh_user_session": fresh_user_session,
            },
        )
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
            persisted_user_message_ids=normalized_message_ids,
            message_count=message_count,
            fresh_user_session=fresh_user_session,
            stream_event_sink=stream_event_sink,
        )
        reservation = TaskReservation(
            reservation_id=str(uuid.uuid4()),
            task_record=record,
            runtime_task=runtime_task,
            update_envelope_cache=update_envelope_cache,
        )

        async with self._state_lock:
            if queue_mode != "interrupt" and self._max_pending_per_session is not None:
                pending = [
                    task
                    for task in self._pending_by_session.get(envelope.session_key, [])
                    if task.task_id not in self._reserved_overflow_victims
                ]
                reservations = self._reservations_by_session.get(envelope.session_key, [])
                if len(pending) + len(reservations) >= self._max_pending_per_session:
                    victim: _RuntimeTask | None = None
                    if effective_policy is PendingOverflowPolicy.DROP_OLDEST:
                        victim = next(
                            (
                                task
                                for task in pending
                                if task.status == AgentTaskStatus.QUEUED
                            ),
                            None,
                        )
                    if victim is None:
                        _emit_metric(
                            "queue_full_errors_total",
                            value=1,
                            session_key=envelope.session_key,
                            policy=str(effective_policy),
                        )
                        raise TaskQueueFullError(
                            session_key=envelope.session_key,
                            max_pending=self._max_pending_per_session,
                        )
                    reservation.overflow_victim = victim
                    self._reserved_overflow_victims.add(victim.task_id)
            self._reservations_by_session.setdefault(envelope.session_key, []).append(
                reservation
            )
        return reservation

    async def abort_reservation(self, reservation: TaskReservation) -> None:
        """Release a reservation after its persistence transaction fails."""

        async with self._state_lock:
            if reservation.activated or reservation.aborted:
                return
            reservations = self._reservations_by_session.get(reservation.session_key, [])
            with contextlib.suppress(ValueError):
                reservations.remove(reservation)
            if not reservations:
                self._reservations_by_session.pop(reservation.session_key, None)
            if reservation.overflow_victim is not None:
                self._reserved_overflow_victims.discard(
                    reservation.overflow_victim.task_id
                )
            reservation.aborted = True

    async def _emit_queued_activation(
        self,
        envelope: RouteEnvelope,
        *,
        task_id: str,
        queue_depth: int,
        queue_position: int,
        run_kind: str,
    ) -> None:
        """Publish the queued lifecycle after irreversible activation."""

        await self._emit(
            envelope.session_key,
            "task.queued",
            {
                "task_id": task_id,
                "session_key": envelope.session_key,
                "queue_depth": queue_depth,
                "queue_position": queue_position,
            },
        )
        await self._notify_task_lifecycle(
            TaskLifecycleEvent(
                phase="queued",
                session_key=envelope.session_key,
                task_id=task_id,
                task_status=AgentTaskStatus.QUEUED,
                run_kind=run_kind,
            )
        )

    async def activate(
        self,
        reservation: TaskReservation,
        *,
        persisted_user_message_id: str | None = None,
        persisted_user_message_ids: list[str] | tuple[str, ...] | None = None,
        fresh_user_session: bool | None = None,
    ) -> TaskHandle:
        """Idempotently activate a reservation after its DB transaction commits."""

        interrupt_targets: list[_RuntimeTask] = []
        victim: _RuntimeTask | None = None
        async with self._state_lock:
            if reservation.aborted:
                raise RuntimeError("Cannot activate an aborted task reservation")
            if reservation.activated:
                return TaskHandle(
                    task_id=reservation.task_id,
                    session_key=reservation.session_key,
                    status=reservation.status,
                )
            reservations = self._reservations_by_session.get(reservation.session_key, [])
            if reservation not in reservations:
                raise RuntimeError("Unknown task reservation")
            reservations.remove(reservation)
            if not reservations:
                self._reservations_by_session.pop(reservation.session_key, None)

            runtime_task = reservation.runtime_task
            activated_message_ids = _ordered_message_ids(
                runtime_task.persisted_user_message_id,
                (
                    *runtime_task.persisted_user_message_ids,
                    *([persisted_user_message_id] if persisted_user_message_id else []),
                    *(persisted_user_message_ids or ()),
                ),
            )
            runtime_task.persisted_user_message_ids = activated_message_ids
            runtime_task.persisted_user_message_id = (
                activated_message_ids[0] if activated_message_ids else None
            )
            if fresh_user_session is not None:
                runtime_task.fresh_user_session = fresh_user_session

            if runtime_task.queue_mode == "interrupt":
                interrupt_targets = [
                    task
                    for task in self._tasks.values()
                    if task.envelope.session_key == reservation.session_key
                    and task.status not in TERMINAL_STATUSES
                ]
                for target in interrupt_targets:
                    target.cancel_requested = True
                    target.cancel_source = "queue_interrupt"
                    target.cancel_reason = "queue_mode_interrupt"

            victim = reservation.overflow_victim
            if victim is not None:
                self._reserved_overflow_victims.discard(victim.task_id)
                pending = self._pending_by_session.get(reservation.session_key, [])
                if (
                    victim.status != AgentTaskStatus.QUEUED
                    or victim not in pending
                ):
                    # The durable acceptance window may be long enough for the
                    # reserved victim to start running. DROP_OLDEST only evicts
                    # waiting work; once the victim has left the pending queue,
                    # its slot has already made room for this replacement.
                    victim = None
                else:
                    victim.cancel_requested = True
                    victim.overflow_dropped = True

            self._tasks[reservation.task_id] = runtime_task
            self._pending_by_session.setdefault(reservation.session_key, []).append(
                runtime_task
            )
            agent_id = runtime_task.envelope.agent_id
            session_key = runtime_task.envelope.session_key
            if agent_id not in self._agent_session_rr:
                self._agent_session_rr[agent_id] = deque()
                self._agent_active_sessions[agent_id] = set()
            active = self._agent_active_sessions[agent_id]
            rr = self._agent_session_rr[agent_id]
            if session_key not in active:
                active.add(session_key)
                rr.append(session_key)
            if reservation.update_envelope_cache:
                self._last_envelope_by_session[session_key] = runtime_task.envelope
            runtime_task.asyncio_task = asyncio.create_task(self._execute(runtime_task))
            reservation.activated = True
            queue_depth = len(self._pending_by_session.get(session_key, []))
            queue_position = queue_depth
            envelope = runtime_task.envelope

        for target in interrupt_targets:
            asyncio_task = target.asyncio_task
            if asyncio_task is not None and not asyncio_task.done():
                asyncio_task.cancel()
        if victim is not None:
            asyncio_task = victim.asyncio_task
            if asyncio_task is not None and not asyncio_task.done():
                asyncio_task.cancel()
            try:
                await self._mark_terminal(
                    victim,
                    AgentTaskStatus.CANCELLED,
                    terminal_reason="dropped_by_overflow",
                )
            except Exception as exc:  # noqa: BLE001 - new task is already active.
                # Activation has crossed its irreversible boundary: the newly
                # accepted task is registered and executing. A best-effort
                # terminal update for the evicted task must not make callers
                # treat that accepted task as rejected or leave the victim's
                # waiters hanging forever.
                log.warning(
                    "task_runtime.overflow_victim_terminal_failed",
                    task_id=victim.task_id,
                    session_key=victim.envelope.session_key,
                    error=str(exc),
                )
            finally:
                victim.done.set()

        _emit_metric(
            "opensquilla_queue_depth",
            value=queue_depth,
            session_key=reservation.session_key,
        )
        try:
            await self._emit_queued_activation(
                envelope,
                task_id=reservation.task_id,
                queue_depth=queue_depth,
                queue_position=queue_position,
                run_kind=runtime_task.run_kind,
            )
        except Exception:  # noqa: BLE001 - acceptance is already durable.
            log.warning(
                "task_runtime.activation_notification_failed",
                task_id=reservation.task_id,
                session_key=reservation.session_key,
                exc_info=True,
            )
        return TaskHandle(
            task_id=reservation.task_id,
            session_key=reservation.session_key,
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
        *,
        source: str | None = None,
        reason: str | None = None,
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
                task.cancel_source = _clean_cancel_detail(source, "unknown")
                task.cancel_reason = _clean_cancel_detail(reason, "cancelled")
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
        attachments: builtins.list[dict[str, Any]] | None = None,
        run_kind: str,
        no_memory_capture: bool,
        semantic_message: str | None = None,
        persisted_user_message_id: str | None = None,
        persisted_user_message_ids: builtins.list[str] | tuple[str, ...] | None = None,
        message_count: int = 1,
    ) -> TaskHandle | None:
        async def persist(
            handle: TaskHandle,
            details: dict[str, Any],
        ) -> None:
            await self._storage.update_agent_task(handle.task_id, details=details)

        collected = await self.try_collect_atomically(
            envelope=envelope,
            message=message,
            attachments=attachments,
            run_kind=run_kind,
            no_memory_capture=no_memory_capture,
            semantic_message=semantic_message,
            persisted_user_message_id=persisted_user_message_id,
            persisted_user_message_ids=persisted_user_message_ids,
            message_count=message_count,
            persist=persist,
        )
        return collected[0] if collected is not None else None

    async def try_collect_atomically(
        self,
        *,
        envelope: RouteEnvelope,
        message: str,
        attachments: builtins.list[dict[str, Any]] | None = None,
        run_kind: str,
        no_memory_capture: bool,
        semantic_message: str | None = None,
        persisted_user_message_id: str | None = None,
        persisted_user_message_ids: builtins.list[str] | tuple[str, ...] | None = None,
        message_count: int = 1,
        persist: Callable[
            [TaskHandle, dict[str, Any]], Awaitable[_CollectResult]
        ],
    ) -> tuple[TaskHandle, _CollectResult] | None:
        """Persist and apply one collect while the candidate remains queued.

        Persistence runs under a per-task claim, never the runtime-wide state
        lock. Running and terminal transitions for the candidate wait for that
        claim; unrelated sessions continue reserving, cancelling, and
        finalising normally. A raised persistence error leaves the candidate
        unchanged. Receipt replays are returned without applying the input a
        second time.
        """

        operation = asyncio.create_task(
            self._try_collect_atomically_impl(
                envelope=envelope,
                message=message,
                attachments=attachments,
                run_kind=run_kind,
                no_memory_capture=no_memory_capture,
                semantic_message=semantic_message,
                persisted_user_message_id=persisted_user_message_id,
                persisted_user_message_ids=persisted_user_message_ids,
                message_count=message_count,
                persist=persist,
            )
        )
        try:
            return await asyncio.shield(operation)
        except asyncio.CancelledError:
            # Once collection begins, settle both persistence and the matching
            # runtime apply before propagating cancellation to the caller.
            await self._wait_for_task_settlement(operation)
            raise

    async def _try_collect_atomically_impl(
        self,
        *,
        envelope: RouteEnvelope,
        message: str,
        attachments: builtins.list[dict[str, Any]] | None,
        run_kind: str,
        no_memory_capture: bool,
        semantic_message: str | None,
        persisted_user_message_id: str | None,
        persisted_user_message_ids: builtins.list[str] | tuple[str, ...] | None,
        message_count: int,
        persist: Callable[
            [TaskHandle, dict[str, Any]], Awaitable[_CollectResult]
        ],
    ) -> tuple[TaskHandle, _CollectResult] | None:
        """Claim, persist, then apply one collection operation."""

        envelope = replace(
            envelope,
            agent_id=normalize_agent_id(envelope.agent_id),
            session_key=canonicalize_session_key(envelope.session_key),
        )
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

        async with candidate.collect_claim:
            # The task may have crossed into RUNNING while this coroutine was
            # waiting for an earlier per-task claim. Re-check under the state
            # lock before any durable side effect.
            async with self._state_lock:
                pending = self._pending_by_session.get(envelope.session_key, [])
                if (
                    candidate not in pending
                    or candidate.queue_mode != "collect"
                    or candidate.status != AgentTaskStatus.QUEUED
                ):
                    return None
                collected_no_memory_capture = candidate.no_memory_capture
                if (
                    no_memory_capture
                    or candidate.run_kind != run_kind
                    or candidate.envelope.input_provenance != envelope.input_provenance
                ):
                    collected_no_memory_capture = True
                collected_message = f"{candidate.message}\n{message}"
                if candidate.semantic_message is not None or semantic_message is not None:
                    first_semantic = (
                        candidate.semantic_message
                        if candidate.semantic_message is not None
                        else candidate.message
                    )
                    next_semantic = (
                        semantic_message if semantic_message is not None else message
                    )
                    collected_semantic_message = f"{first_semantic}\n{next_semantic}"
                else:
                    collected_semantic_message = None
                collected_message_ids = _ordered_message_ids(
                    candidate.persisted_user_message_id,
                    (
                        *candidate.persisted_user_message_ids,
                        *(
                            [persisted_user_message_id]
                            if persisted_user_message_id
                            else []
                        ),
                        *(persisted_user_message_ids or ()),
                    ),
                )
                collected_message_count = candidate.message_count + max(
                    1, int(message_count)
                )
                details = {
                    "source_name": candidate.envelope.source_name,
                    "input_provenance": candidate.envelope.input_provenance,
                    "metadata": candidate.envelope.metadata,
                    "collected": True,
                    "message_count": collected_message_count,
                    "no_memory_capture": collected_no_memory_capture,
                    "persisted_user_message_id": (
                        collected_message_ids[0] if collected_message_ids else None
                    ),
                    "persisted_user_message_ids": collected_message_ids,
                    "fresh_user_session": candidate.fresh_user_session,
                }
                handle = TaskHandle(
                    task_id=candidate.task_id,
                    session_key=envelope.session_key,
                    status=AgentTaskStatus.QUEUED,
                )

            persisted = await persist(handle, details)
            if getattr(persisted, "replayed", False) is not True:
                # The claim prevents running/terminal transitions while the DB
                # operation settles. Apply every aggregate field together only
                # after a non-replay commit.
                async with self._state_lock:
                    candidate.no_memory_capture = collected_no_memory_capture
                    candidate.message = collected_message
                    candidate.attachments.extend(list(attachments or []))
                    candidate.semantic_message = collected_semantic_message
                    candidate.persisted_user_message_ids = collected_message_ids
                    candidate.persisted_user_message_id = (
                        collected_message_ids[0] if collected_message_ids else None
                    )
                    candidate.message_count = collected_message_count
            return handle, persisted

    async def _execute(self, task: _RuntimeTask) -> None:
        session_key = task.envelope.session_key
        write_lock = self._session_locks.setdefault(session_key, asyncio.Lock())
        execution_lock = self._session_execution_locks.setdefault(session_key, asyncio.Lock())
        try:
            async with execution_lock:
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
                heartbeat_task: asyncio.Task[None] | None = None
                try:
                    await self._acquire_fair_slot(task)
                    acquired = True
                    async with write_lock:
                        pass
                    heartbeat_task = self._start_running_heartbeat(task)
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
                        persisted_user_message_ids=tuple(
                            task.persisted_user_message_ids
                        ),
                        fresh_user_session=task.fresh_user_session,
                        stream_event_sink=task.stream_event_sink,
                        assistant_message_sink=(
                            task.capture_terminal_assistant_message
                            if task.run_kind == "channel_turn"
                            else None
                        ),
                    )
                    await self._run_turn_handler_with_write_lock_bypass(
                        run,
                        write_lock=write_lock,
                    )
                    if heartbeat_task is not None:
                        await self._stop_running_heartbeat(heartbeat_task)
                        heartbeat_task = None
                    if acquired:
                        await self._release_slot(task)
                        acquired = False
                    await self._mark_terminal(
                        task,
                        AgentTaskStatus.SUCCEEDED,
                        terminal_reason="completed",
                    )
                finally:
                    if heartbeat_task is not None:
                        await self._stop_running_heartbeat(heartbeat_task)
                    if acquired:
                        await self._release_slot(task)
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

    async def _run_turn_handler_with_write_lock_bypass(
        self,
        run: TaskRun,
        *,
        write_lock: asyncio.Lock,
    ) -> None:
        """Run the handler while TurnRunner transcript writes use short locks."""
        from opensquilla.engine.runtime import (
            _SESSION_LOCK_BYPASS_ONLY,
            _SESSION_LOCK_OWNER,
        )

        current_task = asyncio.current_task()
        prev_map = _SESSION_LOCK_OWNER.get(None)
        new_map: dict[int, Any] = dict(prev_map or {})
        if current_task is not None:
            new_map[id(write_lock)] = current_task
        owner_token = _SESSION_LOCK_OWNER.set(new_map)
        prev_bypass = _SESSION_LOCK_BYPASS_ONLY.get(None)
        new_bypass = set(prev_bypass or set())
        new_bypass.add(id(write_lock))
        bypass_token = _SESSION_LOCK_BYPASS_ONLY.set(new_bypass)
        try:
            if self._turn_hard_deadline_s is not None:
                deadline_start = time.monotonic()
                try:
                    await asyncio.wait_for(
                        self._turn_handler(run),
                        timeout=self._turn_hard_deadline_s,
                    )
                except TimeoutError as exc:
                    # Only reclassify when the hard-deadline budget was actually
                    # exhausted. A TimeoutError from inside the handler should
                    # keep its original cause.
                    elapsed = time.monotonic() - deadline_start
                    if elapsed + 0.01 >= self._turn_hard_deadline_s:
                        raise _TurnHardDeadlineExceeded(
                            deadline_s=self._turn_hard_deadline_s,
                        ) from exc
                    raise
            else:
                await self._turn_handler(run)
        finally:
            _SESSION_LOCK_BYPASS_ONLY.reset(bypass_token)
            _SESSION_LOCK_OWNER.reset(owner_token)

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

        # Update storage and emit running metric outside the condition lock. A
        # collect claim can keep this await open; if cancellation or persistence
        # failure wins that race, release the slot claimed above before the
        # caller's ``acquired`` flag has been set.
        try:
            marked_running = await self._mark_running(task)
        except BaseException:
            await self._release_slot(task)
            raise
        if not marked_running:
            await self._release_slot(task)
            raise asyncio.CancelledError
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

    def _start_running_heartbeat(
        self, task: _RuntimeTask
    ) -> asyncio.Task[None] | None:
        interval = self._running_heartbeat_interval_s
        if interval is None:
            return None
        return asyncio.create_task(
            self._heartbeat_running_task(task, interval),
            name=f"opensquilla-task-heartbeat:{task.task_id}",
        )

    async def _stop_running_heartbeat(self, heartbeat_task: asyncio.Task[None]) -> None:
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            return

    async def _heartbeat_running_task(
        self,
        task: _RuntimeTask,
        interval: float,
    ) -> None:
        while True:
            await asyncio.sleep(interval)
            async with self._state_lock:
                still_running = (
                    not task.terminal_emitted
                    and task.status == AgentTaskStatus.RUNNING
                    and self._running_by_session.get(task.envelope.session_key) is task
                )
            if not still_running:
                return
            try:
                await self._storage.update_agent_task(
                    task.task_id,
                    updated_at=_epoch_time_ms(),
                )
            except Exception as exc:  # noqa: BLE001 - heartbeat is best-effort
                log.warning(
                    "task_runtime.running_heartbeat_failed",
                    task_id=task.task_id,
                    session_key=task.envelope.session_key,
                    error=str(exc),
                )

    async def _mark_running(self, task: _RuntimeTask) -> bool:
        """Move one task to RUNNING after any active collect claim settles."""

        async with task.collect_claim:
            return await self._mark_running_claimed(task)

    async def _mark_running_claimed(self, task: _RuntimeTask) -> bool:
        async with self._state_lock:
            if (
                task.terminal_emitted
                or task.status in TERMINAL_STATUSES
                or task.cancel_requested
            ):
                return False
            task.status = AgentTaskStatus.RUNNING
            self._remove_pending(task)
            self._running_by_session[task.envelope.session_key] = task
        await self._storage.update_agent_task(
            task.task_id,
            status=AgentTaskStatus.RUNNING,
            started_at=_epoch_time_ms(),
        )
        await self._emit(
            task.envelope.session_key,
            "task.running",
            {"task_id": task.task_id, "session_key": task.envelope.session_key},
        )
        await self._notify_task_lifecycle(
            TaskLifecycleEvent(
                phase="running",
                session_key=task.envelope.session_key,
                task_id=task.task_id,
                task_status=AgentTaskStatus.RUNNING,
                run_kind=task.run_kind,
            )
        )
        return True

    async def _mark_terminal(
        self,
        task: _RuntimeTask,
        status: AgentTaskStatus,
        *,
        terminal_reason: str,
        error_class: str | None = None,
        error_message: str | None = None,
    ) -> None:
        """Finalize one task after any active collect claim settles."""

        async with task.collect_claim:
            await self._mark_terminal_claimed(
                task,
                status,
                terminal_reason=terminal_reason,
                error_class=error_class,
                error_message=error_message,
            )

    async def _mark_terminal_claimed(
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
            if self._last_envelope_by_session.get(task.envelope.session_key) is task.envelope:
                self._last_envelope_by_session.pop(task.envelope.session_key, None)
            # Keep the short write lock stable for this session. Popping it can
            # split callers across old/new lock objects while callbacks or
            # late lifecycle events still reference the old one. The dict grows
            # at most by unique session_keys, which is acceptable.
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
        if (
            (
                status == AgentTaskStatus.TIMEOUT
                and terminal_reason != "hard_deadline_exceeded"
            )
            or terminal_reason == "timeout"
            or is_context_payload_too_large(terminal_payload)
            or (
                terminal_reason == "output_truncated"
                or error_class == "provider_output_truncated"
            )
        ):
            error_class, error_message = sanitize_agent_error(
                terminal_payload,
                fallback_error_class=error_class,
                fallback_error_message=error_message or "Agent error",
            )
            terminal_payload["error_class"] = error_class
            terminal_payload["error_message"] = error_message
        try:
            await self._storage.update_agent_task(
                task.task_id,
                status=status,
                finished_at=_epoch_time_ms(),
                terminal_reason=terminal_reason,
                error_class=error_class,
                error_message=error_message,
                **await self._terminal_details_update(
                    task,
                    status=status,
                    terminal_reason=terminal_reason,
                    error_class=error_class,
                    error_message=error_message,
                ),
            )
            payload: dict[str, Any] = {
                "task_id": task.task_id,
                "session_key": task.envelope.session_key,
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
        finally:
            # Keep the runtime task discoverable until the durable status is
            # settled. Otherwise wait() can race the state pop and return the
            # previous persisted status (for example RUNNING after cancellation).
            task.done.set()
            async with self._state_lock:
                if self._tasks.get(task.task_id) is task:
                    self._tasks.pop(task.task_id, None)
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

    async def _terminal_details_update(
        self,
        task: _RuntimeTask,
        *,
        status: AgentTaskStatus,
        terminal_reason: str,
        error_class: str | None,
        error_message: str | None,
    ) -> dict[str, Any]:
        outcome = _subagent_group_outcome_from_provenance(task.envelope.input_provenance)
        existing = await self._storage.get_agent_task(task.task_id)
        current_details = getattr(existing, "details", None)
        details = dict(current_details) if isinstance(current_details, dict) else {}
        cancellation: dict[str, str] | None = None
        if status == AgentTaskStatus.CANCELLED:
            cancellation = {
                "source": task.cancel_source
                or ("overflow_drop" if task.overflow_dropped else "unknown"),
                "reason": task.cancel_reason
                or ("overflow_drop" if task.overflow_dropped else terminal_reason),
            }
            details["cancellation"] = cancellation
        if status == AgentTaskStatus.SUCCEEDED:
            details["turn_outcome"] = completed_outcome().to_dict()
            if task.terminal_assistant_message_content is not None:
                # This is a compact durable channel outbox payload. It keeps
                # delivery exact after compaction/reset and avoids inferring
                # ownership from unrelated assistant writers in the session.
                details["terminal_assistant_message_content"] = (
                    task.terminal_assistant_message_content
                )
                if task.terminal_assistant_message_id is not None:
                    details["terminal_assistant_message_id"] = (
                        task.terminal_assistant_message_id
                    )
        else:
            turn_outcome = outcome_from_error(
                code=terminal_reason if terminal_reason != "error" else error_class,
                message=error_message,
                error_class=error_class,
            ).to_dict()
            if cancellation is not None:
                turn_outcome["cancellation_source"] = cancellation["source"]
            details["turn_outcome"] = turn_outcome
        if outcome is not None:
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


def _epoch_time_ms() -> int:
    return int(time.time() * 1000)
