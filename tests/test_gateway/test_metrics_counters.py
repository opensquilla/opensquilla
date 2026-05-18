"""Tests for the four core metrics emitted via structured logging.

The four counter names are fixed: ``opensquilla_queue_depth``,
``in_flight_turns_total``, ``turn_cancellations_total``, and
``queue_full_errors_total``. The log format must contain
``metric=<name> value=<int>``. Coverage includes triggering each event
and asserting structlog field values, plus a regex check on the format.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock

import pytest
import structlog
import structlog.testing

from opensquilla.gateway.routing import RouteEnvelope, SourceKind
from opensquilla.gateway.task_runtime import TaskQueueFullError, TaskRuntime
from opensquilla.session.models import AgentTaskRecord


@contextmanager
def _capture_metric_logs():
    old_config = structlog.get_config()
    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.NOTSET))
    try:
        with structlog.testing.capture_logs() as captured:
            yield captured
    finally:
        structlog.configure(**old_config)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
        for k, v in kwargs.items():
            if hasattr(rec, k):
                object.__setattr__(rec, k, v)

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
    max_pending_per_session: int | None = 64,
) -> TaskRuntime:
    async def _default_handler(_run: Any) -> None:
        pass

    return TaskRuntime(
        storage=_make_storage(),
        turn_handler=turn_handler or _default_handler,
        max_concurrency=max_concurrency,
        max_pending_per_session=max_pending_per_session,
    )


# ---------------------------------------------------------------------------
# all_four_counters_emit
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_all_four_counters_emit() -> None:
    """Each of the 4 core metric events fires at least once with correct fields."""
    with _capture_metric_logs() as captured:
        # --- opensquilla_queue_depth: emitted on successful enqueue ---
        rt = _make_runtime()
        env = _make_envelope("agent-1::sess-metrics-1")
        handle = await rt.enqueue(env, "hello")
        await rt.wait(handle.task_id, timeout=2.0)

        # --- in_flight_turns_total: emitted when task enters _execute ---
        # (same enqueue above already triggers it; verify below)

        # --- queue_full_errors_total: enqueue when queue is full ---
        # Block the first task so pending queue can fill up
        gate = asyncio.Event()

        async def _blocking_handler(_run: Any) -> None:
            await gate.wait()

        rt_blocked = _make_runtime(
            turn_handler=_blocking_handler,
            max_concurrency=1,
            max_pending_per_session=1,
        )
        env_b = _make_envelope("agent-1::sess-metrics-3")
        h1 = await rt_blocked.enqueue(env_b, "first")
        # Give the first task time to start running and leave pending queue
        await asyncio.sleep(0.05)
        # Second enqueue fills pending slot
        h2 = await rt_blocked.enqueue(env_b, "second")
        # Third enqueue must raise queue full
        with pytest.raises(TaskQueueFullError):
            await rt_blocked.enqueue(env_b, "third")

        # --- turn_cancellations_total: cancel a queued/running task ---
        gate2 = asyncio.Event()

        async def _blocking_handler2(_run: Any) -> None:
            await gate2.wait()

        rt_cancel = _make_runtime(
            turn_handler=_blocking_handler2,
            max_concurrency=1,
        )
        env_c = _make_envelope("agent-1::sess-metrics-4")
        hc = await rt_cancel.enqueue(env_c, "cancel-me")
        await asyncio.sleep(0.05)
        await rt_cancel.cancel(task_id=hc.task_id)
        gate2.set()
        await rt_cancel.wait(hc.task_id, timeout=2.0)

        # Unblock blocked runtime
        gate.set()
        await rt_blocked.wait(h1.task_id, timeout=2.0)
        await rt_blocked.wait(h2.task_id, timeout=2.0)

    # Extract metric events from captured logs
    metric_events = {e["metric"]: e for e in captured if "metric" in e}

    # 1. opensquilla_queue_depth
    assert "opensquilla_queue_depth" in metric_events, (
        "Expected opensquilla_queue_depth metric to be emitted"
    )
    qd = metric_events["opensquilla_queue_depth"]
    assert isinstance(qd["value"], int), "opensquilla_queue_depth value must be int"
    assert "session_key" in qd

    # 2. in_flight_turns_total
    assert "in_flight_turns_total" in metric_events, (
        "Expected in_flight_turns_total metric to be emitted"
    )
    inf = metric_events["in_flight_turns_total"]
    assert inf["value"] == 1, "in_flight_turns_total value must be 1 (cumulative increment)"
    assert "session_key" in inf

    # 3. turn_cancellations_total
    assert "turn_cancellations_total" in metric_events, (
        "Expected turn_cancellations_total metric to be emitted"
    )
    tc = metric_events["turn_cancellations_total"]
    assert tc["value"] == 1
    assert tc.get("reason") in ("interrupt", "user_cancel", "timeout", "reset"), (
        f"Unexpected reason label: {tc.get('reason')}"
    )

    # 4. queue_full_errors_total
    assert "queue_full_errors_total" in metric_events, (
        "Expected queue_full_errors_total metric to be emitted"
    )
    qf = metric_events["queue_full_errors_total"]
    assert qf["value"] == 1
    assert "session_key" in qf


# ---------------------------------------------------------------------------
# log_format_regex
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_log_format_regex() -> None:
    """Captured log entries for metrics must have metric=<name> and value=<int>."""
    metric_name_re = re.compile(
        r"^(opensquilla_queue_depth|in_flight_turns_total|"
        r"turn_cancellations_total|queue_full_errors_total)$"
    )

    with _capture_metric_logs() as captured:
        rt = _make_runtime()
        env = _make_envelope("agent-1::sess-regex-1")
        h = await rt.enqueue(env, "regex-test")
        await rt.wait(h.task_id, timeout=2.0)

    metric_logs = [e for e in captured if "metric" in e]
    assert metric_logs, "Expected at least one metric log entry"

    for entry in metric_logs:
        assert "metric" in entry, f"Missing 'metric' key in {entry}"
        assert "value" in entry, f"Missing 'value' key in {entry}"
        assert metric_name_re.match(entry["metric"]), (
            f"metric name '{entry['metric']}' does not match locked name pattern"
        )
        assert isinstance(entry["value"], int), (
            f"value must be int, got {type(entry['value'])}"
        )
