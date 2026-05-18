"""Lookup boundary tests for runtime task access."""

from __future__ import annotations

import inspect
from types import SimpleNamespace
from typing import Any

import pytest

from opensquilla.gateway.background_completion import (
    _delivery_target_from_task_runtime,
)
from opensquilla.gateway.routing import ReplyTarget, RouteEnvelope, SourceKind
from opensquilla.gateway.task_runtime import TaskRuntime
from opensquilla.gateway.task_runtime_state import TaskRuntimeState
from opensquilla.session.models import AgentTaskRecord

PARENT = "agent:main:channel:parent"
PARENT_TASK = "task-parent"


class _Storage:
    def __init__(self) -> None:
        self.records: dict[str, AgentTaskRecord] = {}

    async def create_agent_task(self, record: AgentTaskRecord) -> None:
        self.records[record.task_id] = record

    async def get_agent_task(self, task_id: str) -> AgentTaskRecord | None:
        return self.records.get(task_id)

    async def list_agent_tasks(self, **_: Any) -> list[AgentTaskRecord]:
        return list(self.records.values())

    async def update_agent_task(self, task_id: str, **fields: Any) -> None:
        record = self.records.get(task_id)
        if record is None:
            return
        for key, value in fields.items():
            if hasattr(record, key):
                object.__setattr__(record, key, value)


def _make_envelope(session_key: str = PARENT) -> RouteEnvelope:
    return RouteEnvelope(
        source_kind=SourceKind.CHANNEL,
        source_name="slack",
        agent_id="main",
        session_key=session_key,
        channel_name="slack",
        channel_id="C-old",
        thread_id="T-old",
        reply_target=ReplyTarget(
            kind="channel",
            channel_name="slack",
            to="C-old",
            thread_id="T-old",
        ),
    )


@pytest.mark.asyncio
async def test_task_runtime_exposes_runtime_task_lookup_facade() -> None:
    async def _handler(_run: Any) -> None:
        pass

    runtime = TaskRuntime(storage=_Storage(), turn_handler=_handler)
    lock = runtime._get_session_lock_for_turn(PARENT)
    await lock.acquire()

    try:
        handle = await runtime.enqueue(_make_envelope(), "hello")
        assert isinstance(runtime._runtime_state, TaskRuntimeState)
        task = runtime.get_runtime_task(handle.task_id)
        assert task is not None
        assert task.task_id == handle.task_id
        assert task.envelope.reply_target is not None
    finally:
        lock.release()
        await runtime.wait(handle.task_id, timeout=2.0)


def test_background_completion_prefers_lookup_facade_and_keeps_legacy_fallback() -> None:
    source = inspect.getsource(_delivery_target_from_task_runtime)

    assert "get_runtime_task" in source
    assert "_tasks" in source


def test_background_completion_lookup_facade_preserves_parent_task_route() -> None:
    runtime = SimpleNamespace(
        get_runtime_task=lambda task_id: SimpleNamespace(envelope=_make_envelope())
        if task_id == PARENT_TASK
        else None
    )

    target = _delivery_target_from_task_runtime(runtime, PARENT_TASK)

    assert target is not None
    assert target.channel_name == "slack"
    assert target.channel_id == "C-old"
    assert target.thread_id == "T-old"


def test_background_completion_legacy_tasks_dict_lookup_still_works() -> None:
    runtime = SimpleNamespace(
        _tasks={
            PARENT_TASK: SimpleNamespace(envelope=_make_envelope()),
        }
    )

    target = _delivery_target_from_task_runtime(runtime, PARENT_TASK)

    assert target is not None
    assert target.channel_name == "slack"
    assert target.channel_id == "C-old"
    assert target.thread_id == "T-old"
