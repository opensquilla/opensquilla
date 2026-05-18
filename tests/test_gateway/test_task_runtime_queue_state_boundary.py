"""TaskRuntime queue behavior through the runtime-state boundary."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest

from opensquilla.gateway.routing import RouteEnvelope, SourceKind
from opensquilla.gateway.task_runtime import TaskQueueFullError, TaskRuntime
from opensquilla.gateway.task_runtime_state import TaskRuntimeState
from opensquilla.session.models import AgentTaskRecord


def _make_envelope(session_key: str = "agent-1::sess-1") -> RouteEnvelope:
    return RouteEnvelope(
        source_kind=SourceKind.WEB,
        source_name="test",
        agent_id="agent-1",
        session_key=session_key,
        input_provenance={"kind": "test"},
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

    async def list_tasks(**_: Any) -> list[AgentTaskRecord]:
        return list(task_db.values())

    storage.create_agent_task = create
    storage.update_agent_task = update
    storage.get_agent_task = get
    storage.list_agent_tasks = list_tasks
    storage.task_db = task_db
    return storage


async def _run_queued(runtime: TaskRuntime, *task_ids: str) -> None:
    for task_id in task_ids:
        await runtime.wait(task_id, timeout=2.0)


def _make_runtime(
    *,
    max_pending_per_session: int | None = 64,
    turn_handler=None,
) -> TaskRuntime:
    async def _default_handler(_run: Any) -> None:
        pass

    return TaskRuntime(
        storage=_make_storage(),
        turn_handler=turn_handler or _default_handler,
        max_pending_per_session=max_pending_per_session,
    )


@pytest.mark.asyncio
async def test_queue_full_check_uses_state_boundary_and_preserves_metric(monkeypatch) -> None:
    emitted: list[tuple[str, int, dict[str, Any]]] = []
    monkeypatch.setattr(
        "opensquilla.gateway.task_runtime._emit_metric",
        lambda name, value=1, **labels: emitted.append((name, value, labels)),
    )
    runtime = _make_runtime(max_pending_per_session=1)
    envelope = _make_envelope("agent-1::queue-boundary")
    lock = runtime._get_session_lock_for_turn(envelope.session_key)
    await lock.acquire()

    try:
        first = await runtime.enqueue(envelope, "first")

        with pytest.raises(TaskQueueFullError) as exc:
            await runtime.enqueue(envelope, "second")

        assert exc.value.session_key == envelope.session_key
        assert isinstance(runtime._runtime_state, TaskRuntimeState)
        assert runtime._runtime_state.pending_count(envelope.session_key) == 1
        assert (
            "queue_full_errors_total",
            1,
            {"session_key": envelope.session_key},
        ) in emitted
    finally:
        lock.release()
        await runtime.wait(first.task_id, timeout=2.0)


@pytest.mark.asyncio
async def test_collect_mode_merge_updates_pending_task_through_state_boundary() -> None:
    runtime = _make_runtime()
    storage = runtime._storage
    envelope = _make_envelope("agent-1::collect-boundary")
    lock = runtime._get_session_lock_for_turn(envelope.session_key)
    await lock.acquire()

    try:
        first = await runtime.enqueue(envelope, "first", mode="collect")
        second = await runtime.enqueue(envelope, "second", mode="collect")

        assert second.task_id == first.task_id
        task = runtime._runtime_state.get_task(first.task_id)
        assert task is not None
        assert task.message == "first\nsecond"
        record = storage.task_db[first.task_id]
        assert record.details["collected"] is True
        assert record.details["message_count"] == 2
    finally:
        lock.release()
        await runtime.wait(first.task_id, timeout=2.0)


@pytest.mark.asyncio
async def test_collect_mode_merge_preserves_no_memory_capture_escalation() -> None:
    runtime = _make_runtime()
    storage = runtime._storage
    envelope = _make_envelope("agent-1::collect-no-memory")
    lock = runtime._get_session_lock_for_turn(envelope.session_key)
    await lock.acquire()

    try:
        first = await runtime.enqueue(envelope, "first", mode="collect")
        second = await runtime.enqueue(
            envelope,
            "second",
            mode="collect",
            no_memory_capture=True,
        )

        assert second.task_id == first.task_id
        task = runtime._runtime_state.get_task(first.task_id)
        assert task is not None
        assert task.no_memory_capture is True
        record = storage.task_db[first.task_id]
        assert record.details["no_memory_capture"] is True
    finally:
        lock.release()
        await runtime.wait(first.task_id, timeout=2.0)


@pytest.mark.asyncio
async def test_send_one_shot_provenance_does_not_poison_cached_envelope() -> None:
    seen_provenance: list[dict[str, Any]] = []
    release = asyncio.Event()

    async def _handler(run: Any) -> None:
        seen_provenance.append(run.input_provenance)
        await release.wait()

    runtime = _make_runtime(turn_handler=_handler)
    envelope = _make_envelope("agent-1::one-shot-provenance")
    envelope.input_provenance["kind"] = "cached"

    first = await runtime.enqueue(envelope, "seed")
    second = await runtime.send(
        envelope.session_key,
        "override",
        provenance={"kind": "one-shot"},
    )
    third = await runtime.send(envelope.session_key, "cached-again")

    release.set()
    await _run_queued(runtime, first.task_id, second.task_id, third.task_id)

    assert seen_provenance == [
        {"kind": "cached"},
        {"kind": "one-shot"},
        {"kind": "cached"},
    ]
