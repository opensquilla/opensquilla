"""Unit tests for the V018 router_decisions ts_ms index migration.

Covers the additive apply (standalone ``ts_ms`` index so the retention
prune, boot rehydration window scan, and unfiltered listing stop
full-scanning the table), the rollback (drops the index, keeps the table
and data), and the dependency edge that reconnects the
``V010__transcript_turn_usage`` leaf to the graph head.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from yoyo import get_backend, read_migrations

from opensquilla.persistence.migrator import apply_pending

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"

V018_ID = "V018__router_decisions_ts_index"


def _open_conn(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _indexes(conn: sqlite3.Connection, table: str) -> set[str]:
    return {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name=?",
            (table,),
        ).fetchall()
        if not row[0].startswith("sqlite_")
    }


def test_v018_apply_creates_ts_index(tmp_path: Path) -> None:
    db = str(tmp_path / "test.sqlite")
    applied = apply_pending(db, MIGRATIONS_DIR)
    assert V018_ID in applied

    conn = _open_conn(db)
    try:
        ix = _indexes(conn, "router_decisions")
        assert "idx_router_decisions_ts" in ix
        # V017's composite index is untouched.
        assert "idx_router_decisions_session_ts" in ix
    finally:
        conn.close()


def test_v018_index_serves_bare_ts_queries(tmp_path: Path) -> None:
    """The retention prune / rehydration / listing shapes filter or order on
    bare ts_ms; the planner must be able to use the new index for them."""
    db = str(tmp_path / "test.sqlite")
    apply_pending(db, MIGRATIONS_DIR)

    conn = _open_conn(db)
    try:
        conn.execute(
            "INSERT INTO router_decisions (decision_id, session_key, ts_ms) "
            "VALUES ('d1', 'agent:main:main', 1000)"
        )
        conn.commit()
        plan = " ".join(
            str(row[3])
            for row in conn.execute(
                "EXPLAIN QUERY PLAN "
                "SELECT decision_id FROM router_decisions WHERE ts_ms >= ?",
                (500,),
            ).fetchall()
        )
        assert "idx_router_decisions_ts" in plan, f"plan was: {plan}"
    finally:
        conn.close()


def test_v018_rollback_drops_index_keeps_table(tmp_path: Path) -> None:
    db = str(tmp_path / "test.sqlite")
    apply_pending(db, MIGRATIONS_DIR)

    conn = _open_conn(db)
    try:
        conn.execute(
            "INSERT INTO router_decisions (decision_id, session_key, ts_ms) "
            "VALUES ('d1', 'agent:main:main', 1000)"
        )
        conn.commit()
    finally:
        conn.close()

    backend = get_backend("sqlite:///" + db)
    try:
        v018 = read_migrations(str(MIGRATIONS_DIR)).filter(
            lambda m: m.id == V018_ID
        )
        with backend.lock():
            backend.rollback_migrations(v018)
    finally:
        backend.connection.close()

    conn = _open_conn(db)
    try:
        assert "idx_router_decisions_ts" not in _indexes(conn, "router_decisions")
        # Table and rows are untouched by the rollback.
        row = conn.execute(
            "SELECT decision_id, ts_ms FROM router_decisions"
        ).fetchone()
        assert row == ("d1", 1000)
    finally:
        conn.close()


def test_v018_version_prefix_is_unique() -> None:
    """Guard against the duplicate-V010 trap: exactly one V018 file."""
    v018_files = sorted(p.name for p in MIGRATIONS_DIR.glob("V018__*.py"))
    assert v018_files == ["V018__router_decisions_ts_index.py"]


def test_v018_reconnects_transcript_usage_leaf() -> None:
    source = (MIGRATIONS_DIR / "V018__router_decisions_ts_index.py").read_text(
        encoding="utf-8"
    )
    assert "V017__router_decisions" in source
    assert "V010__transcript_turn_usage" in source
