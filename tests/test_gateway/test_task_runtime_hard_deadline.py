"""Hard-deadline breaker tests for TaskRuntime.

Covers the behavior when a turn handler exceeds ``turn_hard_deadline_s``,
the breaker fires, releases the OUTER per-session lock, marks the
record TIMEOUT with ``terminal_reason="hard_deadline_exceeded"``,
and lets the next message dispatch successfully.

Tests are designed to be deterministic — they use explicit asyncio
Events to gate handler progress, and choose hard deadlines that are
several orders of magnitude shorter than test wait timeouts so flake
risk stays inside the asyncio scheduler, not in real wall clock.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any
from unittest.mock import MagicMock

import pytest

from opensquilla.gateway.routing import RouteEnvelope, SourceKind
from opensquilla.gateway.task_runtime import TaskRuntime
from opensquilla.session.models import AgentTaskRecord, AgentTaskStatus


def _make_envelope(
    session_key: str = "agent-1::sess-deadline",
    *,
    agent_id: str = "agent-1",
) -> RouteEnvelope:
    return RouteEnvelope(
        source_kind=SourceKind.WEB,
        source_name="test",
        agent_id=agent_id,
        session_key=session_key,
        input_provenance={"kind": "test"},
    )


def _make_storage() -> Any:
    storage = MagicMock()
    task_db: dict[str, AgentTaskRecord] = {}
    storage.updates = []

    async def create(record: AgentTaskRecord) -> None:
        task_db[record.task_id] = record

    async def update(task_id: str, **kwargs: Any) -> None:
        storage.updates.append((task_id, dict(kwargs)))
        rec = task_db.get(task_id)
        if rec is None:
            return
        for key, value in kwargs.items():
            if hasattr(rec, key):
                object.__setattr__(rec, key, value)

    async def get(task_id: str) -> AgentTaskRecord | None:
        return task_db.get(task_id)

    async def list_tasks(**_: Any) -> list[AgentTaskRecord]:
        return list(task_db.values())

    storage.create_agent_task = create
    storage.update_agent_task = update
    storage.get_agent_task = get
    storage.list_agent_tasks = list_tasks
    return storage


def _make_runtime(
    *,
    turn_handler: Callable[..., Awaitable[Any]],
    turn_hard_deadline_s: float | None,
    running_heartbeat_interval_s: float | None = 30.0,
    max_concurrency: int = 1,
) -> TaskRuntime:
    return TaskRuntime(
        storage=_make_storage(),
        turn_handler=turn_handler,
        max_concurrency=max_concurrency,
        max_pending_per_session=8,
        turn_hard_deadline_s=turn_hard_deadline_s,
        running_heartbeat_interval_s=running_heartbeat_interval_s,
    )


@pytest.mark.asyncio
async def test_turn_hard_deadline_breaker_fires_and_marks_timeout() -> None:
    """A turn that never finishes is force-terminated by the breaker.

    The record must record TIMEOUT status with the hard-deadline reason,
    the lock must be released so a follow-up turn proceeds, and the
    breaker must surface a TimeoutError-classified terminal payload.
    """
    handler_started = asyncio.Event()
    handler_release = asyncio.Event()

    async def hung_handler(_run: Any) -> None:
        handler_started.set()
        await handler_release.wait()

    rt = _make_runtime(
        turn_handler=hung_handler,
        turn_hard_deadline_s=0.05,
    )

    env = _make_envelope("agent-1::sess-hung")
    handle = await rt.enqueue(env, "hi")

    # Wait long enough for the breaker to fire. We allow a generous wall
    # clock window (1 s) for the 0.05 s breaker so a slow CI scheduler
    # cannot mistakenly assert a missed timeout.
    record = await rt.wait(handle.task_id, timeout=2.0)

    assert record.status == AgentTaskStatus.TIMEOUT
    assert record.terminal_reason == "hard_deadline_exceeded"
    assert record.error_class == "_TurnHardDeadlineExceeded"
    assert "hard deadline" in (record.error_message or "")

    # The lock must be released — release the gating event so the
    # original handler exits cleanly even though the runtime already
    # marked the record terminal.
    handler_release.set()


@pytest.mark.asyncio
async def test_dispatch_after_breaker_proceeds_for_same_session() -> None:
    """After the breaker fires, the next message on the same session runs."""
    first_started = asyncio.Event()
    first_release = asyncio.Event()
    second_completed = asyncio.Event()

    async def handler(run: Any) -> None:
        if run.message == "first":
            first_started.set()
            await first_release.wait()
        else:
            second_completed.set()

    rt = _make_runtime(
        turn_handler=handler,
        turn_hard_deadline_s=0.05,
    )

    env = _make_envelope("agent-1::sess-followup")

    first = await rt.enqueue(env, "first")
    await asyncio.wait_for(first_started.wait(), timeout=1.0)
    second = await rt.enqueue(env, "second")

    first_record = await rt.wait(first.task_id, timeout=2.0)
    assert first_record.status == AgentTaskStatus.TIMEOUT
    assert first_record.terminal_reason == "hard_deadline_exceeded"

    second_record = await rt.wait(second.task_id, timeout=2.0)
    assert second_record.status == AgentTaskStatus.SUCCEEDED
    assert second_completed.is_set()

    first_release.set()


@pytest.mark.asyncio
async def test_no_deadline_keeps_legacy_behaviour() -> None:
    """When deadline is None the runtime never injects the breaker."""
    handler_started = asyncio.Event()
    handler_release = asyncio.Event()

    async def slow_handler(_run: Any) -> None:
        handler_started.set()
        await handler_release.wait()

    rt = _make_runtime(
        turn_handler=slow_handler,
        turn_hard_deadline_s=None,
    )

    env = _make_envelope("agent-1::sess-no-deadline")
    handle = await rt.enqueue(env, "hi")
    await asyncio.wait_for(handler_started.wait(), timeout=1.0)

    # No breaker means the task is still running after a generous wait.
    with pytest.raises(asyncio.TimeoutError):
        await rt.wait(handle.task_id, timeout=0.2)

    handler_release.set()
    record = await rt.wait(handle.task_id, timeout=2.0)
    assert record.status == AgentTaskStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_running_task_heartbeat_refreshes_updated_at_until_terminal() -> None:
    handler_started = asyncio.Event()
    handler_release = asyncio.Event()
    storage = _make_storage()

    async def slow_handler(_run: Any) -> None:
        handler_started.set()
        await handler_release.wait()

    rt = TaskRuntime(
        storage=storage,
        turn_handler=slow_handler,
        max_concurrency=1,
        max_pending_per_session=8,
        turn_hard_deadline_s=None,
        running_heartbeat_interval_s=0.02,
    )

    env = _make_envelope("agent-1::sess-heartbeat")
    handle = await rt.enqueue(env, "hi")
    await asyncio.wait_for(handler_started.wait(), timeout=1.0)
    await asyncio.sleep(0.07)

    heartbeat_updates = [
        fields
        for task_id, fields in storage.updates
        if task_id == handle.task_id and set(fields) == {"updated_at"}
    ]
    assert heartbeat_updates

    handler_release.set()
    record = await rt.wait(handle.task_id, timeout=2.0)
    assert record.status == AgentTaskStatus.SUCCEEDED

    update_count_after_terminal = len(storage.updates)
    await asyncio.sleep(0.05)
    assert len(storage.updates) == update_count_after_terminal


@pytest.mark.asyncio
async def test_handler_finishing_before_deadline_is_unaffected() -> None:
    """Tasks that complete before the deadline succeed normally."""

    async def fast_handler(_run: Any) -> None:
        return None

    rt = _make_runtime(
        turn_handler=fast_handler,
        turn_hard_deadline_s=2.0,
    )

    env = _make_envelope("agent-1::sess-fast")
    handle = await rt.enqueue(env, "hi")
    record = await rt.wait(handle.task_id, timeout=2.0)
    assert record.status == AgentTaskStatus.SUCCEEDED
    assert record.terminal_reason == "completed"


@pytest.mark.asyncio
async def test_running_turn_does_not_hold_session_write_lock() -> None:
    handler_started = asyncio.Event()
    handler_release = asyncio.Event()

    async def slow_handler(_run: Any) -> None:
        handler_started.set()
        await handler_release.wait()

    rt = _make_runtime(
        turn_handler=slow_handler,
        turn_hard_deadline_s=None,
    )

    env = _make_envelope("agent-1::sess-write-lock-free")
    handle = await rt.enqueue(env, "hi")
    await asyncio.wait_for(handler_started.wait(), timeout=1.0)

    lock = rt._get_session_lock_for_turn(env.session_key)
    await asyncio.wait_for(lock.acquire(), timeout=0.2)
    lock.release()

    handler_release.set()
    record = await rt.wait(handle.task_id, timeout=2.0)
    assert record.status == AgentTaskStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_slot_wait_does_not_hold_waiting_session_write_lock() -> None:
    first_started = asyncio.Event()
    first_release = asyncio.Event()

    async def handler(run: Any) -> None:
        if run.session_key.endswith("busy"):
            first_started.set()
            await first_release.wait()

    rt = _make_runtime(
        turn_handler=handler,
        turn_hard_deadline_s=None,
        max_concurrency=1,
    )

    busy = _make_envelope("agent-1::sess-busy")
    waiting = _make_envelope("agent-1::sess-waiting")
    busy_handle = await rt.enqueue(busy, "first")
    await asyncio.wait_for(first_started.wait(), timeout=1.0)

    waiting_handle = await rt.enqueue(waiting, "second")
    await asyncio.sleep(0.05)

    lock = rt._get_session_lock_for_turn(waiting.session_key)
    await asyncio.wait_for(lock.acquire(), timeout=0.2)
    lock.release()

    first_release.set()
    assert (await rt.wait(busy_handle.task_id, timeout=2.0)).status == AgentTaskStatus.SUCCEEDED
    assert (await rt.wait(waiting_handle.task_id, timeout=2.0)).status == AgentTaskStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_inner_timeout_not_reclassified_as_hard_deadline() -> None:
    """A TimeoutError raised *inside* the handler before the deadline fires
    must escape as-is and must NOT be reclassified as _TurnHardDeadlineExceeded.

    The task's terminal_reason should reflect the actual cause (``"timeout"``)
    rather than ``"hard_deadline_exceeded"``.
    """

    async def instantly_timing_out_handler(_run: Any) -> None:
        # Raise a bare asyncio.TimeoutError immediately — elapsed is ~0 s,
        # far less than the 5 s hard deadline.
        raise TimeoutError("inner tool timed out")

    rt = _make_runtime(
        turn_handler=instantly_timing_out_handler,
        turn_hard_deadline_s=5.0,
    )

    env = _make_envelope("agent-1::sess-inner-timeout")
    handle = await rt.enqueue(env, "hi")
    record = await rt.wait(handle.task_id, timeout=2.0)

    # Must NOT be reclassified as a hard-deadline miss.
    assert record.terminal_reason != "hard_deadline_exceeded"
    assert record.error_class != "_TurnHardDeadlineExceeded"

    # The status should be TIMEOUT (the bare TimeoutError outer handler fires).
    assert record.status == AgentTaskStatus.TIMEOUT
    assert record.terminal_reason == "timeout"


def test_invalid_turn_hard_deadline_rejected() -> None:
    """Negative or zero deadlines must be rejected at construction time."""

    async def noop_handler(_run: Any) -> None:
        return None

    with pytest.raises(ValueError, match="turn_hard_deadline_s"):
        TaskRuntime(
            storage=_make_storage(),
            turn_handler=noop_handler,
            turn_hard_deadline_s=0.0,
        )

    with pytest.raises(ValueError, match="turn_hard_deadline_s"):
        TaskRuntime(
            storage=_make_storage(),
            turn_handler=noop_handler,
            turn_hard_deadline_s=-0.1,
        )
