"""End-to-end: MetaOrchestrator + MetaRunWriter wiring."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from opensquilla.persistence.meta_run_writer import open_meta_run_writer
from opensquilla.persistence.migrator import apply_pending
from opensquilla.skills.meta.types import MetaMatch, MetaPlan, MetaResult, MetaStep

MIGRATIONS_DIR = Path(__file__).resolve().parents[1].parent / "migrations"


@pytest.fixture
def writer_db(tmp_path: Path):
    db = str(tmp_path / "test.db")
    apply_pending(db, MIGRATIONS_DIR)
    w = open_meta_run_writer(db)
    yield w
    w.close()


def _stub_runner_for(outputs: dict[str, str]):
    from opensquilla.skills.meta.events import _StepDone

    async def _runner(step, effective_skill, inputs, outputs_so_far):
        text = outputs.get(step.id, f"output-of-{step.id}")
        if text == "__FAIL__":
            raise RuntimeError(f"{step.id} exploded")
        yield _StepDone(text=text)
    return _runner


async def _drive_orchestrator(writer, plan: MetaPlan, outputs: dict[str, str]) -> MetaResult:
    from opensquilla.skills.meta.orchestrator import MetaOrchestrator

    async def stub_skill_loader_dummy():
        return None

    orch = MetaOrchestrator(
        agent_runner=lambda *a, **kw: None,
        skill_loader=stub_skill_loader_dummy,
        run_writer=writer,
        triggered_by="soft_meta_invoke",
        session_key="sess-test",
        turn_id="turn-test",
    )

    # Patch dispatch to use stub
    orch._dispatch_step_stream = _stub_runner_for(outputs)  # type: ignore[assignment]

    async def empty_preface(step_id, effective_skill):
        if False:
            yield None
        return
    orch._yield_skill_view_preface = empty_preface  # type: ignore[assignment]

    match = MetaMatch(plan=plan, inputs={"user_message": "hi"})
    final: MetaResult | None = None
    async for item in orch.iter_events(match):
        if isinstance(item, MetaResult):
            final = item
    return final or MetaResult(ok=False, error="no result")


@pytest.mark.asyncio
async def test_linear_success_writes_run_and_steps(writer_db) -> None:
    plan = MetaPlan(
        name="linear",
        triggers=("t",),
        priority=10,
        steps=(
            MetaStep(id="s1", skill="alpha", kind="agent"),
            MetaStep(id="s2", skill="beta", kind="agent", depends_on=("s1",)),
        ),
    )
    result = await _drive_orchestrator(writer_db, plan, outputs={"s1": "A", "s2": "B"})
    assert result.ok

    runs = writer_db.list_runs(name="linear")
    assert len(runs) == 1
    run = writer_db.get_run(runs[0].run_id)
    assert run is not None
    assert run.status == "ok"
    assert run.triggered_by == "soft_meta_invoke"
    assert run.session_key == "sess-test"
    assert {s.step_id for s in run.steps} == {"s1", "s2"}
    assert all(s.status == "ok" for s in run.steps)


@pytest.mark.asyncio
async def test_on_failure_records_substituted(writer_db) -> None:
    """C3: original step gets status='substituted', substitute gets own ok."""
    plan = MetaPlan(
        name="failover",
        triggers=("t",),
        priority=10,
        steps=(
            MetaStep(id="primary", skill="alpha", kind="agent", on_failure="backup"),
            MetaStep(id="backup",  skill="beta",  kind="agent"),
        ),
    )
    await _drive_orchestrator(writer_db, plan, outputs={"primary": "__FAIL__", "backup": "OK"})
    runs = writer_db.list_runs(name="failover")
    run = writer_db.get_run(runs[0].run_id)
    assert run is not None
    by_id = {s.step_id: s for s in run.steps}
    assert by_id["primary"].status == "substituted"
    assert by_id["primary"].substitute_step_id == "backup"
    assert by_id["backup"].status == "ok"


@pytest.mark.asyncio
async def test_hard_failure_marks_step_failed(writer_db) -> None:
    """codex-a P2 fix: hard step failure (no on_failure) marks the step row as 'failed'."""
    plan = MetaPlan(
        name="hard-fail", triggers=("t",), priority=10,
        steps=(MetaStep(id="boom", skill="alpha", kind="agent"),),
    )
    await _drive_orchestrator(writer_db, plan, outputs={"boom": "__FAIL__"})
    runs = writer_db.list_runs(name="hard-fail")
    run = writer_db.get_run(runs[0].run_id)
    assert run is not None
    assert run.status == "failed"
    # Critical: step row must be 'failed' not 'running'
    assert run.steps[0].status == "failed"
    assert run.steps[0].error  # non-empty


@pytest.mark.asyncio
async def test_cancellation_marks_cancelled(writer_db) -> None:
    """W5: orchestrator cancelled mid-run → status='cancelled'."""
    plan = MetaPlan(
        name="slow", triggers=("t",), priority=10,
        steps=(MetaStep(id="s1", skill="alpha", kind="agent"),),
    )
    from opensquilla.skills.meta.orchestrator import MetaOrchestrator
    orch = MetaOrchestrator(
        agent_runner=lambda *a, **kw: None,
        skill_loader=lambda: None,
        run_writer=writer_db,
        triggered_by="soft_meta_invoke",
        session_key=None, turn_id=None,
    )

    dispatch_started = asyncio.Event()

    async def slow_dispatch(*args, **kwargs):
        dispatch_started.set()
        await asyncio.sleep(10)
        if False:
            yield None

    async def empty_preface(step_id, effective_skill):
        if False:
            yield None
        return

    orch._dispatch_step_stream = slow_dispatch  # type: ignore[assignment]
    orch._yield_skill_view_preface = empty_preface  # type: ignore[assignment]
    match = MetaMatch(plan=plan, inputs={})

    async def consume():
        async for _ in orch.iter_events(match):
            pass

    task = asyncio.create_task(consume())
    await asyncio.wait_for(dispatch_started.wait(), timeout=2.0)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    runs = writer_db.list_runs(name="slow")
    assert len(runs) == 1
    assert runs[0].status == "cancelled"


@pytest.mark.asyncio
async def test_run_writer_none_legacy_path(writer_db) -> None:
    """Regression: run_writer=None means zero rows written."""
    from opensquilla.skills.meta.orchestrator import MetaOrchestrator
    plan = MetaPlan(
        name="legacy", triggers=("t",), priority=10,
        steps=(MetaStep(id="s1", skill="alpha", kind="agent"),),
    )
    orch = MetaOrchestrator(
        agent_runner=lambda *a, **kw: None, skill_loader=lambda: None,
    )
    orch._dispatch_step_stream = _stub_runner_for({"s1": "X"})  # type: ignore[assignment]

    async def empty_preface(step_id, effective_skill):
        if False:
            yield None
        return
    orch._yield_skill_view_preface = empty_preface  # type: ignore[assignment]

    match = MetaMatch(plan=plan, inputs={})
    async for _ in orch.iter_events(match):
        pass

    assert writer_db.list_runs(name="legacy") == []
