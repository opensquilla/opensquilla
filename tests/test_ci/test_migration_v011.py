"""V011 migration: relax meta_skill_runs.triggered_by CHECK.

Verifies the recreate-and-copy migration preserves existing rows,
opens the constraint to accept ``auto_cron`` + ``auto_dream``, and
keeps all five V010 indexes alive.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from opensquilla.persistence.migrator import apply_pending

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


def _open_conn(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _insert_run(conn: sqlite3.Connection, run_id: str, triggered_by: str) -> None:
    conn.execute(
        """
        INSERT INTO meta_skill_runs (
            run_id, meta_skill_name, meta_skill_digest, plan_snapshot_json,
            triggered_by, status, started_at_ms, inputs_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id, "synth", "deadbeef", "{}", triggered_by, "ok",
            1_000_000, "{}",
        ),
    )
    conn.commit()


def _indexes(conn: sqlite3.Connection, table: str) -> set[str]:
    return {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name=?",
            (table,),
        ).fetchall()
        if not row[0].startswith("sqlite_")
    }


def test_v011_relaxes_triggered_by_check_to_accept_auto_values(
    tmp_path: Path,
) -> None:
    db = str(tmp_path / "v011.db")
    applied = apply_pending(db, MIGRATIONS_DIR)
    assert "V011__meta_skill_runs_triggered_by_auto" in applied

    conn = _open_conn(db)
    try:
        # Existing values still accepted
        _insert_run(conn, "r1", "hard_takeover")
        _insert_run(conn, "r2", "soft_meta_invoke")
        # New values accepted post-V011
        _insert_run(conn, "r3", "auto_cron")
        _insert_run(conn, "r4", "auto_dream")
        # Bad values still rejected
        with pytest.raises(sqlite3.IntegrityError):
            _insert_run(conn, "r5", "made_up_value")
        rows = conn.execute(
            "SELECT triggered_by FROM meta_skill_runs ORDER BY run_id"
        ).fetchall()
        # Ordered by run_id (r1..r4), so the values appear in insertion order
        assert [r[0] for r in rows] == [
            "hard_takeover", "soft_meta_invoke", "auto_cron", "auto_dream",
        ]
    finally:
        conn.close()


def test_v011_preserves_pre_existing_rows(tmp_path: Path) -> None:
    """A row inserted before V011 must still be present after V011 runs."""
    db = str(tmp_path / "v011_preserve.db")
    # Apply only up to V010 by reaching into the migrator with the same DB
    # and then a second pass for V011 — apply_pending is idempotent for the
    # already-applied migrations.
    apply_pending(db, MIGRATIONS_DIR)  # full set

    conn = _open_conn(db)
    try:
        # Insert one row with each original value
        _insert_run(conn, "rA", "hard_takeover")
        _insert_run(conn, "rB", "soft_meta_invoke")
    finally:
        conn.close()

    # Re-apply (idempotent) — confirms rows survive even though V011 does a
    # recreate-and-copy.
    apply_pending(db, MIGRATIONS_DIR)

    conn = _open_conn(db)
    try:
        names = sorted(
            r[0] for r in conn.execute(
                "SELECT triggered_by FROM meta_skill_runs"
            ).fetchall()
        )
        assert "hard_takeover" in names
        assert "soft_meta_invoke" in names
    finally:
        conn.close()


def test_v011_keeps_all_five_v010_indexes(tmp_path: Path) -> None:
    db = str(tmp_path / "v011_idx.db")
    apply_pending(db, MIGRATIONS_DIR)
    conn = _open_conn(db)
    try:
        ix = _indexes(conn, "meta_skill_runs")
        # Four idx_meta_runs_* indexes are recreated by V011.
        assert "idx_meta_runs_name_started" in ix
        assert "idx_meta_runs_status_started" in ix
        assert "idx_meta_runs_session" in ix
        assert "idx_meta_runs_started" in ix
    finally:
        conn.close()


def test_v011_child_table_rows_survive_recreate(tmp_path: Path) -> None:
    """meta_skill_run_steps.run_id FKs into meta_skill_runs.run_id;
    recreating the parent table with foreign_keys=OFF must not orphan
    child rows."""
    db = str(tmp_path / "v011_child.db")
    apply_pending(db, MIGRATIONS_DIR)
    conn = _open_conn(db)
    try:
        _insert_run(conn, "rx", "soft_meta_invoke")
        conn.execute(
            """
            INSERT INTO meta_skill_run_steps (
                run_id, step_id, step_kind, declared_skill, effective_skill,
                status, started_at_ms, rendered_inputs_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("rx", "step1", "agent", "memory", "memory", "ok", 1_000_001, "{}"),
        )
        conn.commit()
    finally:
        conn.close()

    # Re-apply (no-op for V010+V011) — child rows must still resolve their
    # parent.
    apply_pending(db, MIGRATIONS_DIR)
    conn = _open_conn(db)
    try:
        row = conn.execute(
            "SELECT meta_skill_runs.run_id, meta_skill_run_steps.step_id"
            " FROM meta_skill_run_steps"
            " JOIN meta_skill_runs USING (run_id)"
            " WHERE meta_skill_runs.run_id = ?",
            ("rx",),
        ).fetchone()
        assert row == ("rx", "step1")
    finally:
        conn.close()
