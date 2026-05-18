"""Boundary tests for TaskRuntime terminal-state extraction."""

from __future__ import annotations

import ast
import importlib
import inspect
from pathlib import Path
from typing import Any

from opensquilla.gateway.routing import RouteEnvelope, SourceKind
from opensquilla.gateway.task_runtime_records import RuntimeTask
from opensquilla.session.models import AgentTaskStatus

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


def _source_for_method(name: str) -> str:
    class_node = _task_runtime_class()
    return ast.unparse(_method(class_node, name))


def _terminal_state_module() -> Any:
    return importlib.import_module("opensquilla.gateway.task_runtime_terminal_state")


def _make_envelope(session_key: str) -> RouteEnvelope:
    return RouteEnvelope(
        source_kind=SourceKind.WEB,
        source_name="test",
        agent_id="agent-1",
        session_key=session_key,
        input_provenance={"kind": "test"},
    )


def _make_task(
    task_id: str,
    status: AgentTaskStatus,
    *,
    session_key: str | None = None,
) -> RuntimeTask:
    return RuntimeTask(
        task_id=task_id,
        envelope=_make_envelope(session_key or f"agent-1::{task_id}"),
        message="hello",
        attachments=[],
        queue_mode="followup",
        run_kind="default",
        no_memory_capture=False,
        status=status,
    )


def test_terminal_state_module_exports_cleanup_helpers() -> None:
    terminal_state = _terminal_state_module()

    assert callable(terminal_state.cleanup_terminal_task_state)
    assert callable(terminal_state.snapshot_unfinished_tasks)
    assert "cleanup_terminal_task_state" in terminal_state.__all__
    assert "snapshot_unfinished_tasks" in terminal_state.__all__


def test_mark_terminal_delegates_state_cleanup() -> None:
    source = _source_for_method("_mark_terminal")

    assert "cleanup_terminal_task_state(" in source
    assert "self._tasks.pop" not in source
    assert "self._running_by_session.pop" not in source
    assert "self._pending_by_session.pop" not in source
    assert "self._last_envelope_by_session.pop" not in source
    assert "self._remove_pending(" not in source


def test_terminal_cleanup_helper_never_touches_session_locks() -> None:
    terminal_state = _terminal_state_module()
    source = inspect.getsource(terminal_state.cleanup_terminal_task_state)

    assert "_session_locks" not in source
    assert "session_locks" not in source


def test_unfinished_snapshot_returns_only_non_terminal_tasks() -> None:
    terminal_state = _terminal_state_module()
    queued = _make_task("queued", AgentTaskStatus.QUEUED)
    running = _make_task("running", AgentTaskStatus.RUNNING)
    succeeded = _make_task("succeeded", AgentTaskStatus.SUCCEEDED)
    failed = _make_task("failed", AgentTaskStatus.FAILED)
    cancelled = _make_task("cancelled", AgentTaskStatus.CANCELLED)
    timeout = _make_task("timeout", AgentTaskStatus.TIMEOUT)
    abandoned = _make_task("abandoned", AgentTaskStatus.ABANDONED)

    unfinished = terminal_state.snapshot_unfinished_tasks(
        {
            task.task_id: task
            for task in (
                queued,
                succeeded,
                running,
                failed,
                cancelled,
                timeout,
                abandoned,
            )
        }
    )

    assert unfinished == [queued, running]
