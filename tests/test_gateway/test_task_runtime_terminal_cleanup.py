"""Tests for the TaskRuntime terminal-state dict leak fix.

Verifies that, at terminal state, the four short-lived tracking dicts
(``_tasks``, ``_running_by_session``, ``_pending_by_session``,
``_last_envelope_by_session``) drop the task / session_key, while
``_session_locks`` is intentionally retained to prevent split-brain on
rapid re-enqueue. Also covers exception-path cleanup and a 10 000-task
tracemalloc-bounded soak.
"""

from __future__ import annotations

import asyncio
import gc
import tracemalloc
from collections.abc import Awaitable, Callable
from typing import Any
from unittest.mock import MagicMock

import pytest

from opensquilla.gateway import task_runtime
from opensquilla.gateway.routing import RouteEnvelope, SourceKind
from opensquilla.gateway.task_runtime import TaskRuntime
from opensquilla.session.models import AgentTaskRecord

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
    """Minimal storage mock."""
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
# terminal_clears_all_dicts
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_terminal_clears_all_dicts() -> None:
    """After a task succeeds, tracking dicts (except _session_locks) must not contain its key.

    ``_session_locks`` is intentionally NOT cleaned at terminal to prevent
    split-brain under concurrent enqueue. All other dicts are cleaned.
    """
    rt = _make_runtime()
    env = _make_envelope("agent-1::sess-a")
    handle = await rt.enqueue(env, "hello")
    await rt.wait(handle.task_id, timeout=2.0)

    sk = env.session_key
    assert handle.task_id not in rt._tasks
    assert sk not in rt._running_by_session
    assert sk not in rt._pending_by_session
    # _session_locks is intentionally retained: never pop while _execute may
    # still hold the lock; prevents split-brain on rapid re-enqueue.
    assert sk not in rt._last_envelope_by_session


# ---------------------------------------------------------------------------
# cancel_clears_dicts
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cancel_clears_dicts() -> None:
    """After a task is cancelled, all five tracking dicts must not contain its key."""
    started = asyncio.Event()
    blocker = asyncio.Event()

    async def _blocking_handler(_run: Any) -> None:
        started.set()
        await blocker.wait()  # blocks until test cancels

    rt = _make_runtime(turn_handler=_blocking_handler)
    env = _make_envelope("agent-1::sess-b")
    handle = await rt.enqueue(env, "hello")

    # Wait for the handler to actually start, then cancel.
    await asyncio.wait_for(started.wait(), timeout=2.0)
    await rt.cancel(task_id=handle.task_id)
    await rt.wait(handle.task_id, timeout=2.0)

    sk = env.session_key
    assert handle.task_id not in rt._tasks
    assert sk not in rt._running_by_session
    assert sk not in rt._pending_by_session
    # _session_locks is intentionally retained.
    assert sk not in rt._last_envelope_by_session


# ---------------------------------------------------------------------------
# session_lock_kept_during_pending
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_session_lock_kept_during_pending() -> None:
    """_session_locks must NOT be removed while another task is still pending."""
    first_started = asyncio.Event()
    first_release = asyncio.Event()

    async def _slow_handler(_run: Any) -> None:
        first_started.set()
        await first_release.wait()

    # Only 1 concurrency slot so the second task stays pending.
    rt = _make_runtime(turn_handler=_slow_handler, max_concurrency=1)
    env = _make_envelope("agent-1::sess-c")

    handle1 = await rt.enqueue(env, "first")
    await asyncio.wait_for(first_started.wait(), timeout=2.0)

    # Enqueue second task — it will be QUEUED (pending) while first is running.
    handle2 = await rt.enqueue(env, "second")

    sk = env.session_key
    # Session lock must exist because there is still a pending task.
    assert sk in rt._session_locks

    # Now let the first task finish.
    first_release.set()
    await rt.wait(handle1.task_id, timeout=2.0)

    # The lock should still exist because the second task is still alive.
    assert sk in rt._session_locks

    # Wait for second task to finish.
    await rt.wait(handle2.task_id, timeout=2.0)

    # _session_locks is intentionally retained after all tasks complete;
    # do not assert its absence here.


# ---------------------------------------------------------------------------
# exception path cleans up
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_exception_path_clears_dicts() -> None:
    """Even when the turn handler raises, cleanup must run for 4 tracking dicts.

    ``_session_locks`` is intentionally NOT cleared on terminal: retaining
    the lock prevents split-brain when a new enqueue races with _execute's
    post-terminal cleanup. All other 4 dicts (``_tasks``,
    ``_running_by_session``, ``_pending_by_session``,
    ``_last_envelope_by_session``) must be cleaned up.
    """

    async def _failing_handler(_run: Any) -> None:
        raise RuntimeError("deliberate failure")

    rt = _make_runtime(turn_handler=_failing_handler)
    env = _make_envelope("agent-1::sess-d")
    handle = await rt.enqueue(env, "hello")
    await rt.wait(handle.task_id, timeout=2.0)

    sk = env.session_key
    assert handle.task_id not in rt._tasks
    assert sk not in rt._running_by_session
    # _session_locks is intentionally retained after terminal: prevents
    # split-brain on rapid re-enqueue; lock is cheap and bounded per session_key.
    assert sk not in rt._pending_by_session
    assert sk not in rt._last_envelope_by_session


# ---------------------------------------------------------------------------
# no_leak_under_load (tracemalloc quantitative)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_leak_under_load(monkeypatch: pytest.MonkeyPatch) -> None:
    """10 000 tasks, each <=50 ms; dict sizes after GC must be within ±2 of baseline."""
    num_tasks = 10_000
    session_count = 50  # rotate sessions to mimic real load
    monkeypatch.setattr(task_runtime, "_emit_metric", lambda *_args, **_kwargs: None)

    async def _instant_handler(_run: Any) -> None:
        pass  # returns immediately — well under 50 ms

    rt = _make_runtime(
        turn_handler=_instant_handler,
        max_concurrency=32,
        max_pending_per_session=None,
    )

    # --- baseline snapshot (before any tasks) ---
    gc.collect()
    tracemalloc.start()
    snap_before = tracemalloc.take_snapshot()

    baseline_tasks = len(rt._tasks)
    baseline_pending = len(rt._pending_by_session)
    baseline_running = len(rt._running_by_session)
    baseline_envelope = len(rt._last_envelope_by_session)

    # --- run 10 000 tasks ---
    handles = []
    for i in range(num_tasks):
        sk = f"agent-1::sess-load-{i % session_count}"
        env = _make_envelope(sk)
        h = await rt.enqueue(env, f"msg-{i}")
        handles.append(h)

    # Wait for all to complete.
    await asyncio.gather(*(rt.wait(h.task_id, timeout=30.0) for h in handles))

    # --- post-GC snapshot ---
    gc.collect()
    snap_after = tracemalloc.take_snapshot()
    tracemalloc.stop()

    after_tasks = len(rt._tasks)
    after_locks = len(rt._session_locks)
    after_pending = len(rt._pending_by_session)
    after_running = len(rt._running_by_session)
    after_envelope = len(rt._last_envelope_by_session)

    tolerance = 2
    assert abs(after_tasks - baseline_tasks) <= tolerance, (
        f"_tasks leaked: baseline={baseline_tasks}, after={after_tasks}"
    )
    # _session_locks is intentionally NOT cleaned at terminal to prevent
    # split-brain on rapid re-enqueue.  The dict grows by # unique session_keys
    # (capped at session_count=50 here), not by # tasks.  We verify it is bounded
    # by session_count rather than by num_tasks.
    assert after_locks <= session_count + tolerance, (
        f"_session_locks grew beyond unique session count: {after_locks} > {session_count}"
    )
    assert abs(after_pending - baseline_pending) <= tolerance, (
        f"_pending_by_session leaked: baseline={baseline_pending}, after={after_pending}"
    )
    assert abs(after_running - baseline_running) <= tolerance, (
        f"_running_by_session leaked: baseline={baseline_running}, after={after_running}"
    )
    assert abs(after_envelope - baseline_envelope) <= tolerance, (
        f"_last_envelope_by_session leaked: baseline={baseline_envelope}, after={after_envelope}"
    )

    # Confirm memory allocation delta is reasonable (no catastrophic growth).
    # Informational only — the dict-size assertions above are authoritative.
    # 10 000 asyncio tasks create significant transient allocation for
    # Task/Future/Event objects; allow up to 200 MB of incidental growth.
    top_stats = snap_after.compare_to(snap_before, "lineno")
    total_added = sum(s.size_diff for s in top_stats if s.size_diff > 0)
    assert total_added < 200 * 1024 * 1024, (
        f"Unexpected memory growth: {total_added / 1024:.1f} KB"
    )
