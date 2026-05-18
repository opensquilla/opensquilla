"""Boundary tests for the TaskRuntime shutdown extraction."""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

import opensquilla.gateway.task_runtime_shutdown as task_runtime_shutdown
from opensquilla.gateway.routing import RouteEnvelope, SourceKind
from opensquilla.gateway.task_runtime import TaskRuntime
from opensquilla.gateway.task_runtime_records import RuntimeTask
from opensquilla.gateway.task_runtime_shutdown import shutdown_task_runtime
from opensquilla.session.models import AgentTaskRecord, AgentTaskStatus

_ROOT = Path(__file__).resolve().parents[2]
_TASK_RUNTIME_PATH = _ROOT / "src" / "opensquilla" / "gateway" / "task_runtime.py"


def _task_runtime_class() -> ast.ClassDef:
    tree = ast.parse(_TASK_RUNTIME_PATH.read_text())
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "TaskRuntime":
            return node
    raise AssertionError("TaskRuntime class not found")


def _method(class_node: ast.ClassDef, name: str) -> ast.AsyncFunctionDef | ast.FunctionDef:
    for item in class_node.body:
        if isinstance(item, ast.AsyncFunctionDef | ast.FunctionDef) and item.name == name:
            return item
    raise AssertionError(f"TaskRuntime.{name} not found")


def _without_docstring(body: list[ast.stmt]) -> list[ast.stmt]:
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        return body[1:]
    return body


def _make_envelope(
    agent_id: str = "agent-shutdown",
    session_key: str = "agent-shutdown::sess-1",
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

    async def list_tasks(**kwargs: Any) -> list[AgentTaskRecord]:
        return list(task_db.values())

    storage.create_agent_task = create
    storage.update_agent_task = update
    storage.get_agent_task = get
    storage.list_agent_tasks = list_tasks
    return storage


def test_shutdown_boundary_exports_shutdown_helper() -> None:
    assert callable(shutdown_task_runtime)


def test_task_runtime_shutdown_is_thin_delegator() -> None:
    class_node = _task_runtime_class()
    method = _method(class_node, "shutdown")
    body = _without_docstring(method.body)
    source = ast.unparse(ast.Module(body=body, type_ignores=[]))

    assert len(body) <= 2, "TaskRuntime.shutdown should delegate to the shutdown boundary"
    assert "shutdown_task_runtime(" in source
    assert "mark_unfinished_abandoned=self._mark_unfinished_abandoned" in source


@pytest.mark.asyncio
async def test_graceful_drain_completes_without_cancelling() -> None:
    task_started = asyncio.Event()
    task_completed: list[str] = []
    task_cancelled: list[str] = []

    async def turn_handler(run: Any) -> None:
        task_started.set()
        try:
            await asyncio.sleep(0.05)
            task_completed.append(run.task_id)
        except asyncio.CancelledError:
            task_cancelled.append(run.task_id)
            raise

    runtime = TaskRuntime(
        storage=_make_storage(),
        turn_handler=turn_handler,
        max_concurrency=2,
    )

    handle = await runtime.enqueue(_make_envelope(), "finish naturally")
    await asyncio.wait_for(task_started.wait(), timeout=2.0)

    await runtime.shutdown(graceful=True, graceful_timeout=1.0)

    assert task_completed == [handle.task_id]
    assert task_cancelled == []


@pytest.mark.asyncio
async def test_graceful_timeout_cancels_and_marks_unfinished_abandoned_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release_cancelled_task = asyncio.Event()
    mark_calls = 0

    async def stubborn_task() -> None:
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            await release_cancelled_task.wait()
            raise

    asyncio_task = asyncio.create_task(stubborn_task())
    await asyncio.sleep(0)
    runtime_task = RuntimeTask(
        task_id="task-stubborn",
        envelope=_make_envelope(),
        message="",
        attachments=[],
        queue_mode="followup",
        run_kind="default",
        no_memory_capture=False,
        status=AgentTaskStatus.RUNNING,
    )
    runtime_task.asyncio_task = asyncio_task

    async def mark_unfinished_abandoned() -> None:
        nonlocal mark_calls
        mark_calls += 1

    async def force_graceful_timeout(awaitable: Any, timeout: float | None = None) -> Any:
        awaitable.add_done_callback(lambda done: done.exception() if not done.cancelled() else None)
        raise TimeoutError

    monkeypatch.setattr(task_runtime_shutdown.asyncio, "wait_for", force_graceful_timeout)

    try:
        await shutdown_task_runtime(
            tasks={runtime_task.task_id: runtime_task},
            state_lock=asyncio.Lock(),
            mark_unfinished_abandoned=mark_unfinished_abandoned,
            graceful=True,
            graceful_timeout=0.01,
            timeout=0.01,
        )
        assert mark_calls == 1
        assert asyncio_task.cancelling()
    finally:
        release_cancelled_task.set()
        try:
            await asyncio_task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_cancel_false_waits_without_issuing_cancellation() -> None:
    task_started = asyncio.Event()
    task_completed: list[str] = []
    task_cancelled: list[str] = []

    async def turn_handler(run: Any) -> None:
        task_started.set()
        try:
            await asyncio.sleep(0.05)
            task_completed.append(run.task_id)
        except asyncio.CancelledError:
            task_cancelled.append(run.task_id)
            raise

    runtime = TaskRuntime(
        storage=_make_storage(),
        turn_handler=turn_handler,
        max_concurrency=2,
    )

    handle = await runtime.enqueue(_make_envelope(), "drain without cancel")
    await asyncio.wait_for(task_started.wait(), timeout=2.0)

    await runtime.shutdown(cancel=False, timeout=1.0)

    assert task_completed == [handle.task_id]
    assert task_cancelled == []
