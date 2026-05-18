"""Task runtime record DTOs and queue error contracts."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from opensquilla.gateway.routing import RouteEnvelope
from opensquilla.session.models import AgentTaskStatus

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
    # Raw user text used as the memory prefetch query when the runtime path
    # needs to diverge from ``message``. Channels
    # set this to the pre-stamping content; web/CLI leave it ``None`` so
    # ``TurnRunner.run`` falls back to ``message`` as the semantic input.
    semantic_message: str | None = None
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


@dataclass
class RuntimeTask:
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
    stream_event_sink: TaskStreamEventSink | None = None
    done: asyncio.Event = field(default_factory=asyncio.Event)
    terminal_emitted: bool = False
    cancel_requested: bool = False
    acquired_slot: bool = False


TaskHandler = Callable[[TaskRun], Awaitable[Any]]
EventEmitter = Callable[[str, str, dict[str, Any]], Awaitable[None]]
TerminalListener = Callable[[Any], Awaitable[None]]


class TaskQueueFullError(RuntimeError):
    """Raised when a session's waiting queue reaches its configured limit."""

    def __init__(self, *, session_key: str, max_pending: int) -> None:
        super().__init__(
            f"task queue overflow for session '{session_key}': "
            f"max_pending_per_session={max_pending}"
        )
        self.session_key = session_key
        self.max_pending = max_pending


__all__ = [
    "EventEmitter",
    "RuntimeTask",
    "TaskHandle",
    "TaskHandler",
    "TaskQueueFullError",
    "TaskRun",
    "TaskStreamEventSink",
    "TerminalListener",
]
