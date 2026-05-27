"""DAO tests for clarify state on MetaRunWriter (PR2)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from yoyo import get_backend, read_migrations

from opensquilla.persistence.meta_run_writer import (
    AwaitingPeek,
    MetaRunWriter,
)


@pytest.fixture
def writer(tmp_path: Path) -> MetaRunWriter:
    db = tmp_path / "test.sqlite"
    backend = get_backend(f"sqlite:///{db}")
    backend.apply_migrations(read_migrations("migrations"))
    conn = sqlite3.connect(db, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return MetaRunWriter(conn)


def _seed_awaiting(writer: MetaRunWriter, *, run_id: str, session_key: str,
                   step_id: str = "collect", since: float = 1700000000.0) -> None:
    schema_json = json.dumps({"mode": "form", "fields": []})
    with writer._lock:
        writer._conn.execute(
            "INSERT INTO meta_skill_runs "
            "(run_id, meta_skill_name, meta_skill_digest, plan_snapshot_json, "
            " triggered_by, session_key, status, started_at_ms, inputs_json, "
            " awaiting_step_id, awaiting_schema_json, awaiting_since, "
            " awaiting_filled_json, step_outputs_json) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (run_id, "tskill", "d", "{}", "soft_meta_invoke", session_key,
             "awaiting_user", 0, "{}", step_id, schema_json, since,
             "{}", "{}"),
        )
        writer._conn.commit()


def test_peek_awaiting_returns_none_for_unknown_session(writer):
    assert writer.peek_awaiting(session_id="nope") is None


def test_peek_awaiting_returns_record_for_matching_session(writer):
    _seed_awaiting(writer, run_id="r1", session_key="S1")
    peek = writer.peek_awaiting(session_id="S1")
    assert peek is not None
    assert isinstance(peek, AwaitingPeek)
    assert peek.run_id == "r1"
    assert peek.step_id == "collect"
    assert peek.awaiting_session_id == "S1"


def test_peek_awaiting_ignores_non_awaiting_status(writer):
    with writer._lock:
        writer._conn.execute(
            "INSERT INTO meta_skill_runs "
            "(run_id, meta_skill_name, meta_skill_digest, plan_snapshot_json, "
            " triggered_by, session_key, status, started_at_ms, inputs_json) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            ("r2", "tskill", "d", "{}", "soft_meta_invoke", "S2",
             "ok", 0, "{}"),
        )
        writer._conn.commit()
    assert writer.peek_awaiting(session_id="S2") is None


def test_try_claim_awaiting_succeeds_for_running_run(writer):
    with writer._lock:
        writer._conn.execute(
            "INSERT INTO meta_skill_runs "
            "(run_id, meta_skill_name, meta_skill_digest, plan_snapshot_json, "
            " triggered_by, session_key, status, started_at_ms, inputs_json) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            ("r1", "t", "d", "{}", "soft_meta_invoke", "S1", "running", 0, "{}"),
        )
        writer._conn.commit()

    ok = writer.try_claim_awaiting(
        run_id="r1",
        step_id="collect",
        schema_json='{"mode":"form","fields":[]}',
        session_id="S1",
        inputs_json='{"user_message":"hi"}',
        step_outputs_json='{}',
        awaiting_since=1700000000.0,
    )
    assert ok is True

    peek = writer.peek_awaiting(session_id="S1")
    assert peek is not None
    assert peek.run_id == "r1"
    assert peek.step_id == "collect"


def test_try_claim_awaiting_fails_when_run_already_finished(writer):
    with writer._lock:
        writer._conn.execute(
            "INSERT INTO meta_skill_runs "
            "(run_id, meta_skill_name, meta_skill_digest, plan_snapshot_json, "
            " triggered_by, session_key, status, started_at_ms, inputs_json) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            ("r1", "t", "d", "{}", "soft_meta_invoke", "S1", "ok", 0, "{}"),
        )
        writer._conn.commit()

    ok = writer.try_claim_awaiting(
        run_id="r1",
        step_id="collect",
        schema_json="{}",
        session_id="S1",
        inputs_json="{}",
        step_outputs_json="{}",
        awaiting_since=0.0,
    )
    assert ok is False
    assert writer.peek_awaiting(session_id="S1") is None


def test_try_claim_awaiting_partial_unique_index_blocks_double_awaiting(writer):
    with writer._lock:
        for run_id in ("r1", "r2"):
            writer._conn.execute(
                "INSERT INTO meta_skill_runs "
                "(run_id, meta_skill_name, meta_skill_digest, plan_snapshot_json, "
                " triggered_by, session_key, status, started_at_ms, inputs_json) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (run_id, "t", "d", "{}", "soft_meta_invoke", "S1",
                 "running", 0, "{}"),
            )
        writer._conn.commit()

    assert writer.try_claim_awaiting(
        run_id="r1", step_id="collect", schema_json="{}",
        session_id="S1", inputs_json="{}", step_outputs_json="{}",
        awaiting_since=0.0,
    ) is True
    assert writer.try_claim_awaiting(
        run_id="r2", step_id="collect", schema_json="{}",
        session_id="S1", inputs_json="{}", step_outputs_json="{}",
        awaiting_since=0.0,
    ) is False


def test_try_claim_resume_wins_on_first_call(writer):
    _seed_awaiting(writer, run_id="r1", session_key="S1")
    payload = writer.try_claim_resume(run_id="r1", session_id="S1")
    assert payload is not None
    assert payload.run_id == "r1"
    assert payload.awaiting_step_id == "collect"
    assert payload.inputs_json == "{}"
    peek_after = writer.peek_awaiting(session_id="S1")
    assert peek_after is None


def test_try_claim_resume_loses_when_already_consumed(writer):
    _seed_awaiting(writer, run_id="r1", session_key="S1")
    first = writer.try_claim_resume(run_id="r1", session_id="S1")
    assert first is not None
    second = writer.try_claim_resume(run_id="r1", session_id="S1")
    assert second is None


def test_try_claim_resume_rejects_session_mismatch(writer):
    _seed_awaiting(writer, run_id="r1", session_key="S1")
    payload = writer.try_claim_resume(run_id="r1", session_id="DIFFERENT")
    assert payload is None
    assert writer.peek_awaiting(session_id="S1") is not None
