"""End-to-end programmatic resume tests (PR3, design §8.3)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from yoyo import get_backend, read_migrations

from opensquilla.persistence.meta_run_writer import MetaRunWriter
from opensquilla.skills.meta.events import _StepDone
from opensquilla.skills.meta.orchestrator import MetaOrchestrator
from opensquilla.skills.meta.plan_serde import to_jsonable
from opensquilla.skills.meta.types import (
    ClarifyField,
    ClarifyStepConfig,
    MetaMatch,
    MetaPlan,
    MetaResult,
    MetaStep,
)


@pytest.fixture
def writer(tmp_path: Path) -> MetaRunWriter:
    db = tmp_path / "test.sqlite"
    backend = get_backend(f"sqlite:///{db}")
    backend.apply_migrations(read_migrations("migrations"))
    conn = sqlite3.connect(db, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return MetaRunWriter(conn)


def _plan_with_collect_then_summary() -> MetaPlan:
    cfg = ClarifyStepConfig(
        mode="form",
        fields=(
            ClarifyField(name="destination", type="string", required=True),
            ClarifyField(name="days", type="int", required=True, min=1, max=14),
            ClarifyField(
                name="additional_notes",
                type="string",
                required=False,
                max_chars=2000,
            ),
        ),
        intro="Trip info needed.",
    )
    return MetaPlan(
        name="trip",
        triggers=("plan a trip",),
        priority=0,
        steps=(
            MetaStep(
                id="collect",
                skill="collect",
                kind="user_input",
                clarify_config=cfg,
            ),
            MetaStep(
                id="summary",
                skill="summarize",
                kind="agent",
                depends_on=("collect",),
                with_args={
                    "context": (
                        "destination={{ inputs.collected.collect.destination }} "
                        "days={{ inputs.collected.collect.days }}"
                    ),
                },
            ),
        ),
    )


def _seed_running_run(writer, plan, run_id="r1", session_key="S1"):
    inputs = {"user_message": "I want to plan a trip", "collected": {}}
    snapshot_json = json.dumps(to_jsonable(plan), sort_keys=True, ensure_ascii=False)
    with writer._lock:
        writer._conn.execute(
            "INSERT INTO meta_skill_runs "
            "(run_id, meta_skill_name, meta_skill_digest, plan_snapshot_json, "
            " triggered_by, session_key, status, started_at_ms, inputs_json) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (run_id, plan.name, "d", snapshot_json, "soft_meta_invoke",
             session_key, "running", 0, json.dumps(inputs)),
        )
        writer._conn.commit()
    return inputs


async def _sv(*_a):
    return
    yield  # type: ignore[unreachable]


@pytest.mark.asyncio
async def test_pause_then_resume_completes_dag(writer):
    plan = _plan_with_collect_then_summary()
    inputs = _seed_running_run(writer, plan)

    dispatched_context: dict[str, dict] = {}

    orch = MetaOrchestrator(
        agent_runner=None,  # type: ignore[arg-type]
        skill_loader=None,
        dao=writer,
    )

    async def _dispatch(step, effective_skill, match_inputs, outputs):
        if step.kind == "user_input":
            async for ev in orch._dispatch_one_step(
                step, effective_skill, match_inputs, outputs,
                run_id="r1", session_id="S1",
            ):
                yield ev
            return
        if step.id == "summary":
            dispatched_context["summary"] = {
                "context_arg": step.with_args.get("context", ""),
                "inputs_user_message": match_inputs.get("user_message"),
                "inputs_collected": match_inputs.get("collected"),
            }
            yield _StepDone(text="summary-done", status="ok")

    match = MetaMatch(plan=plan, inputs=inputs)
    result = await orch.run_once(
        match,
        run_id="r1",
        session_id="S1",
        dispatch_step_stream=_dispatch,
        yield_skill_view_preface=_sv,
    )
    assert isinstance(result, MetaResult)
    assert result.paused is True
    assert result.paused_payload is not None
    assert result.paused_payload.step_id == "collect"

    result2 = await orch.resume(
        run_id="r1",
        session_id="S1",
        filled_fields={"destination": "Tokyo", "days": 5},
        dispatch_step_stream=_dispatch,
        yield_skill_view_preface=_sv,
    )
    assert result2.paused is False
    assert result2.ok is True

    sm = dispatched_context["summary"]
    assert sm["inputs_user_message"] == "I want to plan a trip"
    assert sm["inputs_collected"]["collect"]["destination"] == "Tokyo"
    assert sm["inputs_collected"]["collect"]["days"] == 5


@pytest.mark.asyncio
async def test_resume_injects_additional_notes_into_downstream_user_message(writer):
    plan = _plan_with_collect_then_summary()
    inputs = _seed_running_run(writer, plan)

    dispatched_context: dict[str, dict] = {}

    orch = MetaOrchestrator(
        agent_runner=None,  # type: ignore[arg-type]
        skill_loader=None,
        dao=writer,
    )

    async def _dispatch(step, effective_skill, match_inputs, outputs):
        if step.kind == "user_input":
            async for ev in orch._dispatch_one_step(
                step, effective_skill, match_inputs, outputs,
                run_id="r1", session_id="S1",
            ):
                yield ev
            return
        if step.id == "summary":
            dispatched_context["summary"] = {
                "inputs_user_message": match_inputs.get("user_message"),
                "inputs_collected": match_inputs.get("collected"),
            }
            yield _StepDone(text="summary-done", status="ok")

    paused = await orch.run_once(
        MetaMatch(plan=plan, inputs=inputs),
        run_id="r1",
        session_id="S1",
        dispatch_step_stream=_dispatch,
        yield_skill_view_preface=_sv,
    )
    assert paused.paused is True

    await orch.resume(
        run_id="r1",
        session_id="S1",
        filled_fields={
            "destination": "Tokyo",
            "days": 5,
            "additional_notes": "Please avoid museums; kid wants trains.",
        },
        dispatch_step_stream=_dispatch,
        yield_skill_view_preface=_sv,
    )

    sm = dispatched_context["summary"]
    assert sm["inputs_collected"]["collect"]["additional_notes"] == (
        "Please avoid museums; kid wants trains."
    )
    assert sm["inputs_user_message"].startswith("I want to plan a trip")
    assert "Additional user notes" in sm["inputs_user_message"]
    assert "Please avoid museums; kid wants trains." in sm["inputs_user_message"]


@pytest.mark.asyncio
async def test_resume_finalizes_run_to_ok_status(writer):
    plan = _plan_with_collect_then_summary()
    inputs = _seed_running_run(writer, plan)

    orch = MetaOrchestrator(
        agent_runner=None, skill_loader=None, dao=writer,  # type: ignore[arg-type]
    )

    async def _dispatch(step, effective_skill, match_inputs, outputs):
        if step.kind == "user_input":
            async for ev in orch._dispatch_one_step(
                step, effective_skill, match_inputs, outputs,
                run_id="r1", session_id="S1",
            ):
                yield ev
            return
        if step.id == "summary":
            yield _StepDone(text="summary-done", status="ok")

    await orch.run_once(
        MetaMatch(plan=plan, inputs=inputs),
        run_id="r1", session_id="S1",
        dispatch_step_stream=_dispatch, yield_skill_view_preface=_sv,
    )
    final = await orch.resume(
        run_id="r1", session_id="S1",
        filled_fields={"destination": "Tokyo", "days": 5},
        dispatch_step_stream=_dispatch, yield_skill_view_preface=_sv,
    )
    assert final.ok is True

    with writer._lock:
        row = writer._conn.execute(
            "SELECT status, ended_at_ms FROM meta_skill_runs WHERE run_id='r1'",
        ).fetchone()
    assert row["status"] == "ok"
    assert row["ended_at_ms"] is not None and row["ended_at_ms"] > 0


@pytest.mark.asyncio
async def test_resume_rejects_unknown_run(writer):
    orch = MetaOrchestrator(
        agent_runner=None, skill_loader=None, dao=writer,  # type: ignore[arg-type]
    )
    result = await orch.resume(
        run_id="does-not-exist",
        session_id="S1",
        filled_fields={},
        dispatch_step_stream=None,
        yield_skill_view_preface=None,
    )
    assert result.ok is False
    assert result.paused is False
    assert result.error is not None
    assert "not found" in result.error.lower() or "race" in result.error.lower()


@pytest.mark.asyncio
async def test_resume_writes_clarify_summary_into_outputs(writer):
    plan = _plan_with_collect_then_summary()
    inputs = _seed_running_run(writer, plan)

    observed_outputs: dict[str, dict] = {}

    orch = MetaOrchestrator(
        agent_runner=None, skill_loader=None, dao=writer,  # type: ignore[arg-type]
    )

    async def _dispatch(step, effective_skill, match_inputs, outputs):
        if step.kind == "user_input":
            async for ev in orch._dispatch_one_step(
                step, effective_skill, match_inputs, outputs,
                run_id="r1", session_id="S1",
            ):
                yield ev
            return
        if step.id == "summary":
            observed_outputs["summary"] = dict(outputs)
            yield _StepDone(text="ok", status="ok")

    paused = await orch.run_once(
        MetaMatch(plan=plan, inputs=inputs),
        run_id="r1", session_id="S1",
        dispatch_step_stream=_dispatch, yield_skill_view_preface=_sv,
    )
    assert paused.paused is True, "test fixture expected pause before resume"
    await orch.resume(
        run_id="r1", session_id="S1",
        filled_fields={"destination": "Tokyo", "days": 5},
        dispatch_step_stream=_dispatch, yield_skill_view_preface=_sv,
    )

    summary_outputs = observed_outputs["summary"]
    collect_md = summary_outputs.get("collect", "")
    assert "destination: Tokyo (from user)" in collect_md
    assert "days: 5 (from user)" in collect_md


@pytest.mark.asyncio
async def test_resume_persists_followup_step_lifecycle_and_usage(writer):
    from opensquilla.engine.usage import UsageTracker
    from opensquilla.persistence.meta_run_writer import summarize_run_record

    plan = _plan_with_collect_then_summary()
    inputs = _seed_running_run(writer, plan)
    tracker = UsageTracker()
    writer.begin_step_sync(
        run_id="r1",
        step=plan.steps[0],
        effective_skill="collect",
        rendered_inputs={},
    )

    orch = MetaOrchestrator(
        agent_runner=None,  # type: ignore[arg-type]
        skill_loader=None,
        dao=writer,
        usage_tracker=tracker,
        session_key="S1",
    )

    async def _dispatch(step, effective_skill, match_inputs, outputs):
        if step.kind == "user_input":
            async for ev in orch._dispatch_one_step(
                step, effective_skill, match_inputs, outputs,
                run_id="r1", session_id="S1",
            ):
                yield ev
            return
        if step.id == "summary":
            tracker.add(
                "S1",
                input_tokens=21,
                output_tokens=9,
                model_id="resume-model",
                billed_cost=0.021,
            )
            yield _StepDone(text="summary-done", status="ok")

    paused = await orch.run_once(
        MetaMatch(plan=plan, inputs=inputs),
        run_id="r1",
        session_id="S1",
        dispatch_step_stream=_dispatch,
        yield_skill_view_preface=_sv,
    )
    assert paused.paused is True, "test fixture expected pause before resume"

    final = await orch.resume(
        run_id="r1",
        session_id="S1",
        filled_fields={"destination": "Tokyo", "days": 5},
        dispatch_step_stream=_dispatch,
        yield_skill_view_preface=_sv,
    )

    assert final.ok is True
    record = writer.get_run("r1")
    assert record is not None
    raw_steps = {step.step_id: step for step in record.steps}
    assert raw_steps["collect"].status == "ok"
    assert "destination: Tokyo" in (raw_steps["collect"].output_text or "")
    summary = summarize_run_record(record)
    by_step = {step["step_id"]: step for step in summary["steps"]}
    assert by_step["collect"]["status"] == "ok"
    assert by_step["summary"]["status"] == "ok"
    assert by_step["summary"]["usage"]["available"] is True
    assert by_step["summary"]["usage"]["input_tokens"] == 21
    assert by_step["summary"]["usage"]["model"] == "resume-model"
