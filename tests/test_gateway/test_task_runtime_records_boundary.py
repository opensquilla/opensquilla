"""Boundary tests for task runtime record ownership."""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path

import opensquilla.gateway.task_runtime as compat_task_runtime
from opensquilla.gateway.routing import RouteEnvelope, SourceKind
from opensquilla.gateway.task_runtime_records import (
    RuntimeTask,
    TaskHandle,
    TaskQueueFullError,
    TaskRun,
)
from opensquilla.session.models import AgentTaskStatus


def _make_envelope() -> RouteEnvelope:
    return RouteEnvelope(
        source_kind=SourceKind.WEB,
        source_name="test",
        agent_id="agent-1",
        session_key="agent-1::session-1",
        input_provenance={"kind": "test"},
    )


def test_task_runtime_keeps_record_compatibility_aliases() -> None:
    assert compat_task_runtime.TaskHandle is TaskHandle
    assert compat_task_runtime.TaskRun is TaskRun
    assert compat_task_runtime._RuntimeTask is RuntimeTask
    assert compat_task_runtime.TaskQueueFullError is TaskQueueFullError


def test_task_runtime_no_longer_defines_record_classes_directly() -> None:
    source_path = (
        Path(__file__).parents[2]
        / "src"
        / "opensquilla"
        / "gateway"
        / "task_runtime.py"
    )
    tree = ast.parse(source_path.read_text())
    top_level_classes = {
        node.name for node in tree.body if isinstance(node, ast.ClassDef)
    }

    assert "TaskHandle" not in top_level_classes
    assert "TaskRun" not in top_level_classes
    assert "_RuntimeTask" not in top_level_classes
    assert "TaskQueueFullError" not in top_level_classes


def test_runtime_task_preserves_mutable_runtime_state_defaults() -> None:
    first = RuntimeTask(
        task_id="task-1",
        envelope=_make_envelope(),
        message="hello",
        attachments=[],
        queue_mode="followup",
        run_kind="default",
        no_memory_capture=False,
    )
    second = RuntimeTask(
        task_id="task-2",
        envelope=_make_envelope(),
        message="hello again",
        attachments=[],
        queue_mode="followup",
        run_kind="default",
        no_memory_capture=False,
    )

    assert first.status is AgentTaskStatus.QUEUED
    assert first.terminal_emitted is False
    assert first.cancel_requested is False
    assert first.acquired_slot is False
    assert isinstance(first.done, asyncio.Event)
    assert isinstance(second.done, asyncio.Event)
    assert first.done is not second.done
    assert not first.done.is_set()
