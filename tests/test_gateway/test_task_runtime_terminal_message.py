from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from unittest.mock import MagicMock

import pytest

from opensquilla.engine.types import ErrorEvent
from opensquilla.gateway.boot import _emit_task_runtime_stream_events
from opensquilla.gateway.routing import RouteEnvelope, SourceKind
from opensquilla.gateway.task_runtime import SubagentCompletionEvent, TaskRuntime
from opensquilla.session.models import AgentTaskRecord, AgentTaskStatus


def _make_envelope(
    session_key: str = "agent-1::sess-1",
    *,
    metadata: dict[str, Any] | None = None,
) -> RouteEnvelope:
    return RouteEnvelope(
        source_kind=SourceKind.WEB,
        source_name="test",
        agent_id="agent-1",
        session_key=session_key,
        input_provenance={"kind": "test"},
        metadata=metadata or {},
    )


def _make_storage() -> Any:
    storage = MagicMock()
    task_db: dict[str, AgentTaskRecord] = {}

    async def create(record: AgentTaskRecord) -> None:
        task_db[record.task_id] = record

    async def update(task_id: str, **kwargs: Any) -> None:
        rec = task_db.get(task_id)
        if rec is None:
            return
        for key, value in kwargs.items():
            if hasattr(rec, key):
                object.__setattr__(rec, key, value)

    async def get(task_id: str) -> AgentTaskRecord | None:
        return task_db.get(task_id)

    storage.create_agent_task = create
    storage.update_agent_task = update
    storage.get_agent_task = get
    return storage


def _make_runtime(
    turn_handler: Callable[..., Awaitable[Any]],
    *,
    event_emitter: Callable[[str, str, dict[str, Any]], Awaitable[None]] | None = None,
    terminal_listener: Callable[[SubagentCompletionEvent], Awaitable[None]] | None = None,
) -> TaskRuntime:
    return TaskRuntime(
        storage=_make_storage(),
        turn_handler=turn_handler,
        event_emitter=event_emitter,
        terminal_listener=terminal_listener,
    )


@pytest.mark.asyncio
async def test_mark_terminal_emits_additive_terminal_message_for_timeout_payload() -> None:
    emitted: list[tuple[str, str, dict[str, Any]]] = []

    async def _emitter(session_key: str, event_name: str, payload: dict[str, Any]) -> None:
        emitted.append((session_key, event_name, payload))

    async def _timeout_handler(_run: Any) -> None:
        raise TimeoutError("Gateway task timeout: Stream idle for more than 60s")

    runtime = _make_runtime(_timeout_handler, event_emitter=_emitter)
    handle = await runtime.enqueue(_make_envelope(), "hello")

    record = await runtime.wait(handle.task_id, timeout=2.0)

    terminal_events = [event for event in emitted if event[1] == "task.timeout"]
    assert len(terminal_events) == 1
    payload = terminal_events[0][2]
    assert payload["task_id"] == handle.task_id
    assert payload["terminal_reason"] == "timeout"
    assert payload["terminal_message"]
    assert "timed out" in payload["terminal_message"].lower()
    assert "Gateway task timeout" not in payload["terminal_message"]
    assert "Stream idle for more than" not in payload["terminal_message"]
    assert record.terminal_reason == "timeout"
    assert record.error_class == "TimeoutError"
    assert record.error_message == "Gateway task timeout: Stream idle for more than 60s"


def test_subagent_completion_payload_adds_terminal_message_for_non_success() -> None:
    event = SubagentCompletionEvent(
        parent_session_key="agent:main:parent",
        child_session_key="agent:worker:child",
        task_id="task-child",
        status=AgentTaskStatus.FAILED,
        terminal_reason="error",
        error_class="RuntimeError",
        error_message="boom",
    )

    payload = event.to_payload()

    assert payload["terminal_reason"] == "error"
    assert payload["error_class"] == "RuntimeError"
    assert payload["error_message"] == "boom"
    assert payload["terminal_message"]
    assert "failed" in payload["terminal_message"].lower()


def test_subagent_completion_payload_keeps_success_payload_unchanged() -> None:
    event = SubagentCompletionEvent(
        parent_session_key="agent:main:parent",
        child_session_key="agent:worker:child",
        task_id="task-child",
        status=AgentTaskStatus.SUCCEEDED,
        terminal_reason="completed",
    )

    assert "terminal_message" not in event.to_payload()


@pytest.mark.asyncio
async def test_task_runtime_stream_error_emits_terminal_message_and_preserves_raw_detail() -> None:
    emitted: list[tuple[str, str, dict[str, Any]]] = []

    async def _stream():
        yield ErrorEvent(
            message="Iteration 1 exceeded iteration_timeout",
            code="iteration_timeout",
        )

    async def _emitter(session_key: str, event_name: str, payload: dict[str, Any]) -> None:
        emitted.append((session_key, event_name, payload))

    with pytest.raises(RuntimeError, match="Iteration 1 exceeded iteration_timeout"):
        await _emit_task_runtime_stream_events(
            _stream(),
            "agent:main:test",
            _emitter,
            stream_event_sink=None,
            idle_timeout=1.0,
            heartbeat_interval=0.0,
        )

    assert emitted == [
        (
            "agent:main:test",
            "session.event.error",
            {
                "message": "The task timed out before it could finish.",
                "code": "iteration_timeout",
                "terminal_message": "The task timed out before it could finish.",
                "terminal_reason": "timeout",
                "error_message": "Iteration 1 exceeded iteration_timeout",
            },
        )
    ]
