"""MetaRunWriter unit tests — round-trip, truncation, thread safety, redaction."""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from opensquilla.persistence.meta_run_writer import (
    MetaRunWriter,
    RunRecord,  # noqa: F401 — explicit public-API surface assertion
    StepRecord,  # noqa: F401 — explicit public-API surface assertion
    _gen_ulid,
    _redact_inputs_json,
    _serialize_plan,
    _truncate,
    open_meta_run_writer,
)
from opensquilla.persistence.migrator import apply_pending
from opensquilla.skills.meta.types import MetaPlan, MetaStep

MIGRATIONS_DIR = Path(__file__).resolve().parents[1].parent / "migrations"


@pytest.fixture
def writer(tmp_path: Path):
    db = str(tmp_path / "test.db")
    apply_pending(db, MIGRATIONS_DIR)
    w = open_meta_run_writer(db)
    yield w
    w.close()


def _make_plan(name: str = "demo") -> MetaPlan:
    return MetaPlan(
        name=name,
        triggers=("demo trigger",),
        priority=50,
        steps=(
            MetaStep(id="s1", skill="alpha", kind="agent"),
            MetaStep(id="s2", skill="beta", kind="agent", depends_on=("s1",)),
        ),
    )


def test_pragmas_set_on_connection(writer: MetaRunWriter) -> None:
    cur = writer._conn.execute("PRAGMA foreign_keys")
    assert cur.fetchone()[0] == 1
    cur = writer._conn.execute("PRAGMA journal_mode")
    assert cur.fetchone()[0].lower() == "wal"
    cur = writer._conn.execute("PRAGMA synchronous")
    assert cur.fetchone()[0] == 1  # NORMAL == 1
    cur = writer._conn.execute("PRAGMA busy_timeout")
    assert cur.fetchone()[0] == 5000


def test_begin_finish_run_roundtrip(writer: MetaRunWriter) -> None:
    plan = _make_plan()
    run_id = writer.begin_run_sync(
        meta_skill_name=plan.name,
        meta_plan=plan,
        triggered_by="soft_meta_invoke",
        inputs={"user_message": "hi"},
        session_key="sess-1",
        turn_id="turn-1",
    )
    assert len(run_id) == 26  # ULID

    from opensquilla.skills.meta.types import MetaResult
    writer.finish_run_sync(
        run_id=run_id,
        status="ok",
        result=MetaResult(ok=True, final_text="hello"),
    )

    record = writer.get_run(run_id)
    assert record is not None
    assert record.meta_skill_name == "demo"
    assert record.triggered_by == "soft_meta_invoke"
    assert record.session_key == "sess-1"
    assert record.status == "ok"
    assert record.final_text == "hello"
    assert record.owner_pid == os.getpid()
    assert record.plan_snapshot_json  # non-empty
    assert len(record.meta_skill_digest) == 64  # sha256 hex


def test_step_lifecycle(writer: MetaRunWriter) -> None:
    plan = _make_plan()
    run_id = writer.begin_run_sync(
        meta_skill_name=plan.name,
        meta_plan=plan,
        triggered_by="hard_takeover",
        inputs={"q": "x"},
        session_key=None,
        turn_id=None,
    )
    writer.begin_step_sync(
        run_id=run_id,
        step=plan.steps[0],
        effective_skill="alpha",
        rendered_inputs={"q": "x"},
    )
    writer.finish_step_sync(
        run_id=run_id,
        step_id="s1",
        status="ok",
        output_text="alpha-output",
    )
    steps = writer.get_steps(run_id)
    assert len(steps) == 1
    assert steps[0].status == "ok"
    assert steps[0].output_text == "alpha-output"
    assert steps[0].effective_skill == "alpha"


def test_llm_chat_step_lifecycle(writer: MetaRunWriter) -> None:
    plan = MetaPlan(
        name="demo",
        triggers=("demo trigger",),
        priority=50,
        steps=(MetaStep(id="baseline", skill="baseline", kind="llm_chat"),),
    )
    run_id = writer.begin_run_sync(
        meta_skill_name=plan.name,
        meta_plan=plan,
        triggered_by="soft_meta_invoke",
        inputs={"user_message": "x"},
        session_key=None,
        turn_id=None,
    )
    writer.begin_step_sync(
        run_id=run_id,
        step=plan.steps[0],
        effective_skill="baseline",
        rendered_inputs={"task": "same task"},
    )
    writer.finish_step_sync(
        run_id=run_id,
        step_id="baseline",
        status="ok",
        output_text="baseline-output",
    )

    steps = writer.get_steps(run_id)
    assert len(steps) == 1
    assert steps[0].step_kind == "llm_chat"
    assert steps[0].status == "ok"
    assert steps[0].output_text == "baseline-output"


def test_on_step_failover_records_substitution(writer: MetaRunWriter) -> None:
    """C3: original failed step gets status='substituted' + substitute_step_id."""
    plan = _make_plan()
    run_id = writer.begin_run_sync(
        meta_skill_name=plan.name,
        meta_plan=plan,
        triggered_by="hard_takeover",
        inputs={},
        session_key=None,
        turn_id=None,
    )
    writer.begin_step_sync(
        run_id=run_id, step=plan.steps[0], effective_skill="alpha", rendered_inputs={},
    )
    writer.on_step_failover_sync(
        run_id=run_id,
        failed_step_id="s1",
        substitute_step_id="s_fallback",
        error="alpha exploded",
    )
    steps = {s.step_id: s for s in writer.get_steps(run_id)}
    assert steps["s1"].status == "substituted"
    assert steps["s1"].substitute_step_id == "s_fallback"
    assert steps["s1"].error == "alpha exploded"


def test_truncate_64kib_utf8_boundary() -> None:
    """W4/§4.2: truncate clips at UTF-8 boundary safely."""
    multibyte = "中" * 30000  # each char = 3 bytes, total 90 KB
    out, truncated = _truncate(multibyte, "x", max_bytes=64 * 1024)
    assert truncated
    assert out is not None
    encoded = out.encode("utf-8")
    assert len(encoded) <= 64 * 1024
    # No malformed UTF-8: round-tripping must succeed
    encoded.decode("utf-8")


def test_truncate_passthrough_for_small() -> None:
    out, truncated = _truncate("hello", "x", max_bytes=64 * 1024)
    assert not truncated
    assert out == "hello"


def test_redactor_redacts_secret_keys() -> None:
    raw = {
        "user_message": "tell me about cats",
        "api_key": "sk-abc123",
        "nested": {"token": "Bearer xyz", "color": "blue"},
        "AUTH_HEADER": "Bearer real-secret",
    }
    out = _redact_inputs_json(raw, max_bytes=64 * 1024)
    parsed = json.loads(out)
    assert parsed["user_message"] == "tell me about cats"
    assert parsed["api_key"] == "[REDACTED]"
    assert parsed["nested"]["token"] == "[REDACTED]"
    assert parsed["nested"]["color"] == "blue"
    assert parsed["AUTH_HEADER"] == "[REDACTED]"


def test_redactor_clips_large_strings() -> None:
    raw = {"huge": "x" * 10_000}
    out = _redact_inputs_json(raw, max_bytes=64 * 1024)
    parsed = json.loads(out)
    assert len(parsed["huge"]) <= 4100  # 4 KiB + suffix


def test_redactor_total_size_budget() -> None:
    raw = {f"k{i}": "x" * 200 for i in range(1000)}
    out = _redact_inputs_json(raw, max_bytes=4 * 1024)
    assert len(out.encode("utf-8")) <= 4 * 1024 + 64  # tiny overhead allowed
    parsed = json.loads(out)
    assert parsed.get("_redaction_overflow") is True


def test_ulid_known_vector_length_and_alphabet() -> None:
    """I4: ULIDs are 26-char Crockford-base32 (no I, L, O, U)."""
    forbidden = set("ILOU")
    for _ in range(100):
        u = _gen_ulid()
        assert len(u) == 26
        assert all(c.isalnum() for c in u)
        assert not (set(u.upper()) & forbidden)


def test_ulid_same_ms_collision_uniqueness() -> None:
    """I4: 1000 ULIDs minted in a tight loop must all be unique."""
    ids = {_gen_ulid() for _ in range(1000)}
    assert len(ids) == 1000


def test_ulid_lexicographic_order_matches_time() -> None:
    """I3: time-ordered ULIDs sort lexicographically same as by start time."""
    import time
    pairs = []
    for _ in range(20):
        pairs.append((time.time_ns(), _gen_ulid()))
        time.sleep(0.005)
    sorted_by_time = [u for _, u in sorted(pairs)]
    sorted_by_ulid = sorted([u for _, u in pairs])
    assert sorted_by_time == sorted_by_ulid


def test_serialize_plan_deterministic() -> None:
    """C5: plan snapshot + digest must be deterministic for same plan."""
    plan1 = _make_plan()
    plan2 = _make_plan()
    snap1, dig1 = _serialize_plan(plan1)
    snap2, dig2 = _serialize_plan(plan2)
    assert snap1 == snap2
    assert dig1 == dig2
    assert len(dig1) == 64


def test_thread_safety_executor(writer: MetaRunWriter) -> None:
    """W1 v2: writer must survive cross-thread access from default ThreadPoolExecutor."""
    plan = _make_plan()
    run_id = writer.begin_run_sync(
        meta_skill_name=plan.name, meta_plan=plan,
        triggered_by="soft_meta_invoke", inputs={}, session_key=None, turn_id=None,
    )

    def _do_step(i: int) -> None:
        step = MetaStep(id=f"par{i}", skill=f"s{i}", kind="agent")
        writer.begin_step_sync(
            run_id=run_id, step=step, effective_skill=f"s{i}", rendered_inputs={},
        )
        writer.finish_step_sync(
            run_id=run_id, step_id=f"par{i}", status="ok", output_text=f"o{i}",
        )

    # ThreadPoolExecutor default (multi-thread) — used to fail with check_same_thread=True
    with ThreadPoolExecutor(max_workers=5) as ex:
        list(ex.map(_do_step, range(20)))

    steps = writer.get_steps(run_id)
    assert len(steps) == 20


def test_cancelled_status_distinct(writer: MetaRunWriter) -> None:
    """W5: cancelled is distinct from failed and ok."""
    plan = _make_plan()
    run_id = writer.begin_run_sync(
        meta_skill_name=plan.name, meta_plan=plan,
        triggered_by="soft_meta_invoke", inputs={}, session_key=None, turn_id=None,
    )
    writer.finish_run_sync(run_id=run_id, status="cancelled", result=None)
    record = writer.get_run(run_id)
    assert record is not None
    assert record.status == "cancelled"
    assert record.final_text is None


def test_writer_failures_dont_raise(tmp_path: Path) -> None:
    """Fail-open contract: writer methods log + swallow."""
    db = str(tmp_path / "test.db")
    apply_pending(db, MIGRATIONS_DIR)
    w = open_meta_run_writer(db)
    w.close()  # connection now closed
    # Subsequent calls must not raise
    w.begin_step_sync(
        run_id="bogus", step=MetaStep(id="s", skill="x", kind="agent"),
        effective_skill="x", rendered_inputs={},
    )  # silently no-ops


def test_purge_for_session_cascades(writer: MetaRunWriter) -> None:
    plan = _make_plan()
    run_id = writer.begin_run_sync(
        meta_skill_name=plan.name, meta_plan=plan,
        triggered_by="soft_meta_invoke", inputs={}, session_key="sess-purge", turn_id=None,
    )
    writer.begin_step_sync(
        run_id=run_id, step=plan.steps[0], effective_skill="alpha", rendered_inputs={},
    )
    writer.finish_step_sync(run_id=run_id, step_id="s1", status="ok", output_text="x")
    writer.finish_run_sync(run_id=run_id, status="ok", result=None)

    removed = writer.purge_for_session("sess-purge")
    assert removed == 1
    assert writer.get_run(run_id) is None
    assert writer.get_steps(run_id) == []


def test_list_runs_filtering_and_ordering(writer: MetaRunWriter) -> None:
    plan = _make_plan()
    ids = []
    for i in range(5):
        rid = writer.begin_run_sync(
            meta_skill_name=plan.name, meta_plan=plan,
            triggered_by="soft_meta_invoke", inputs={"i": i},
            session_key=f"s{i % 2}", turn_id=None,
        )
        writer.finish_run_sync(run_id=rid, status="ok" if i % 2 == 0 else "failed", result=None)
        ids.append(rid)

    all_runs = writer.list_runs(limit=10)
    assert len(all_runs) == 5
    # I3: list ordered by started_at_ms DESC, run_id DESC → newest first
    assert all_runs[0].run_id == ids[-1]

    failed = writer.list_runs(status="failed")
    assert len(failed) == 2
    assert all(r.status == "failed" for r in failed)

    by_session = writer.list_runs(session_key="s0")
    assert len(by_session) == 3
