from __future__ import annotations

import importlib
import inspect
from collections.abc import Awaitable, Callable
from typing import Any
from unittest.mock import MagicMock

import pytest

from opensquilla.gateway.routing import RouteEnvelope, SourceKind
from opensquilla.gateway.task_runtime import TaskRuntime
from opensquilla.session.models import AgentTaskRecord, AgentTaskStatus


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
    return storage


def _make_runtime(
    turn_handler: Callable[..., Awaitable[Any]] | None = None,
    max_concurrency: int = 4,
) -> TaskRuntime:
    async def _default_handler(_run: Any) -> None:
        pass

    return TaskRuntime(
        storage=_make_storage(),
        turn_handler=turn_handler or _default_handler,
        max_concurrency=max_concurrency,
    )


def test_execution_module_exports_helper_and_callbacks() -> None:
    execution = importlib.import_module("opensquilla.gateway.task_runtime_execution")

    assert hasattr(execution, "TaskRuntimeExecutionCallbacks")
    assert hasattr(execution, "execute_task_lifecycle")


def test_task_runtime_execute_is_thin_delegator() -> None:
    source = inspect.getsource(TaskRuntime._execute)

    assert "execute_task_lifecycle" in source
    assert "TaskRuntimeExecutionCallbacks" in source
    assert "TaskRun(" not in source
    assert "terminal_reason=\"completed\"" not in source
    assert len(source.splitlines()) <= 24


@pytest.mark.asyncio
async def test_cancel_before_start_marks_cancelled_with_terminal_reason() -> None:
    runtime = _make_runtime()
    envelope = _make_envelope("agent-1::cancel-before-start")
    lock = runtime._get_session_lock_for_turn(envelope.session_key)
    await lock.acquire()
    handle = await runtime.enqueue(envelope, "hello")
    task = runtime._tasks[handle.task_id]
    task.cancel_requested = True
    lock.release()

    await runtime.wait(handle.task_id, timeout=2.0)

    record = await runtime.status(handle.task_id)
    assert record.status == AgentTaskStatus.CANCELLED
    assert record.terminal_reason == "cancelled_before_start"


@pytest.mark.asyncio
async def test_slot_release_still_happens_if_turn_handler_raises() -> None:
    async def _failing_handler(_run: Any) -> None:
        raise RuntimeError("boom")

    runtime = _make_runtime(turn_handler=_failing_handler, max_concurrency=1)
    handle = await runtime.enqueue(_make_envelope("agent-1::handler-raises"), "hello")

    record = await runtime.wait(handle.task_id, timeout=2.0)

    assert record.status == AgentTaskStatus.FAILED
    assert record.terminal_reason == "error"
    assert runtime._global_in_flight == 0
    assert runtime._agent_in_flight == {}
