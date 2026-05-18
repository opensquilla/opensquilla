"""Boundary tests for TaskRuntimeState extraction."""

from __future__ import annotations

import ast
import importlib
import inspect
from pathlib import Path

from opensquilla.gateway.task_runtime import (
    SubagentCompletionEvent,
    TaskHandle,
    TaskQueueFullError,
    TaskRun,
    _RuntimeTask,
)

_ROOT = Path(__file__).resolve().parents[2]
_TASK_RUNTIME_PATH = _ROOT / "src" / "opensquilla" / "gateway" / "task_runtime.py"

_RAW_STATE_ATTRS = {
    "_tasks",
    "_pending_by_session",
    "_running_by_session",
    "_last_envelope_by_session",
    "_state_lock",
}


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


def _assigned_self_attrs(method: ast.AsyncFunctionDef | ast.FunctionDef) -> set[str]:
    assigned: set[str] = set()
    for node in ast.walk(method):
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets.extend(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets.append(node.target)
        for target in targets:
            if (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "self"
            ):
                assigned.add(target.attr)
    return assigned


def test_task_runtime_state_module_owns_raw_runtime_indexes() -> None:
    state_module = importlib.import_module("opensquilla.gateway.task_runtime_state")

    assert hasattr(state_module, "TaskRuntimeState")
    assert "TaskRuntimeState" in state_module.__all__

    state_source = inspect.getsource(state_module.TaskRuntimeState)
    for attr in _RAW_STATE_ATTRS:
        assert attr in state_source

    runtime_init = _method(_task_runtime_class(), "__init__")
    assigned = _assigned_self_attrs(runtime_init)
    assert _RAW_STATE_ATTRS.isdisjoint(assigned)
    assert "_runtime_state" in assigned


def test_task_runtime_keeps_public_facade_and_compatibility_imports() -> None:
    assert TaskRun.__name__ == "TaskRun"
    assert TaskHandle.__name__ == "TaskHandle"
    assert TaskQueueFullError.__name__ == "TaskQueueFullError"
    assert SubagentCompletionEvent.__name__ == "SubagentCompletionEvent"
    assert _RuntimeTask.__name__ == "RuntimeTask"

    class_node = _task_runtime_class()
    assigned = _assigned_self_attrs(_method(class_node, "__init__"))
    assert "_session_locks" in assigned
    assert any(
        isinstance(item, ast.FunctionDef) and item.name == "_get_session_lock_for_turn"
        for item in class_node.body
    )


def test_task_runtime_state_has_no_storage_or_delivery_responsibilities() -> None:
    state_module = importlib.import_module("opensquilla.gateway.task_runtime_state")
    source = inspect.getsource(state_module)

    assert "_storage" not in source
    assert "create_agent_task" not in source
    assert "update_agent_task" not in source
    assert "build_task_terminal_payload" not in source
    assert "notify_subagent_terminal" not in source
    assert "WebSocket" not in source
    assert "_session_locks" not in source
