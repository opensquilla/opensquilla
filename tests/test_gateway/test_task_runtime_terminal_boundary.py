from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest

from opensquilla.gateway.task_runtime import (
    SubagentCompletionEvent as CompatibilitySubagentCompletionEvent,
)
from opensquilla.gateway.task_runtime_terminal import (
    SubagentCompletionEvent,
    build_task_terminal_payload,
    notify_subagent_terminal,
)
from opensquilla.session.models import AgentTaskStatus


def test_task_runtime_keeps_subagent_completion_compatibility_alias() -> None:
    assert CompatibilitySubagentCompletionEvent is SubagentCompletionEvent


def test_task_runtime_no_longer_defines_subagent_completion_event() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    task_runtime_path = repo_root / "src" / "opensquilla" / "gateway" / "task_runtime.py"
    module = ast.parse(task_runtime_path.read_text(encoding="utf-8"))

    class_names = {
        node.name for node in module.body if isinstance(node, ast.ClassDef)
    }

    assert "SubagentCompletionEvent" not in class_names


def test_build_task_terminal_payload_preserves_failure_detail() -> None:
    payload = build_task_terminal_payload(
        AgentTaskStatus.FAILED,
        terminal_reason="error",
        error_class="RuntimeError",
        error_message="boom",
    )

    assert payload["terminal_reason"] == "error"
    assert payload["error_class"] == "RuntimeError"
    assert payload["error_message"] == "boom"
    assert payload["terminal_message"]
    assert "failed" in payload["terminal_message"].lower()


def test_build_task_terminal_payload_omits_success_terminal_message() -> None:
    payload = build_task_terminal_payload(
        AgentTaskStatus.SUCCEEDED,
        terminal_reason="completed",
    )

    assert payload == {"terminal_reason": "completed"}


@pytest.mark.asyncio
async def test_notify_subagent_terminal_emits_only_for_subagent_with_parent() -> None:
    events: list[SubagentCompletionEvent] = []

    async def _listener(event: SubagentCompletionEvent) -> None:
        events.append(event)

    base: dict[str, Any] = {
        "listener": _listener,
        "child_session_key": "agent:worker:child",
        "task_id": "task-child",
        "status": AgentTaskStatus.FAILED,
        "terminal_reason": "error",
        "agent_id": "worker",
        "parent_task_id": "task-parent",
        "error_class": "RuntimeError",
        "error_message": "boom",
    }

    await notify_subagent_terminal(
        run_kind="default",
        parent_session_key="agent:main:parent",
        **base,
    )
    await notify_subagent_terminal(
        run_kind="subagent",
        parent_session_key=None,
        **base,
    )
    await notify_subagent_terminal(
        run_kind="subagent",
        parent_session_key="",
        **base,
    )

    assert events == []

    await notify_subagent_terminal(
        run_kind="subagent",
        parent_session_key="agent:main:parent",
        **base,
    )

    assert len(events) == 1
    event = events[0]
    assert event.parent_session_key == "agent:main:parent"
    assert event.child_session_key == "agent:worker:child"
    assert event.task_id == "task-child"
    assert event.status is AgentTaskStatus.FAILED
    assert event.terminal_reason == "error"
    assert event.agent_id == "worker"
    assert event.parent_task_id == "task-parent"
    assert event.error_class == "RuntimeError"
    assert event.error_message == "boom"


@pytest.mark.asyncio
async def test_notify_subagent_terminal_ignores_listener_exceptions() -> None:
    async def _listener(_event: SubagentCompletionEvent) -> None:
        raise RuntimeError("listener failed")

    await notify_subagent_terminal(
        _listener,
        run_kind="subagent",
        parent_session_key="agent:main:parent",
        child_session_key="agent:worker:child",
        task_id="task-child",
        status=AgentTaskStatus.FAILED,
        terminal_reason="error",
    )
