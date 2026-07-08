"""V018 migration: durable per-turn error records (turn_errors)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from yoyo import get_backend, read_migrations

from opensquilla.persistence.migrator import apply_pending

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def test_v018_creates_turn_errors_table(tmp_path: Path) -> None:
    db = str(tmp_path / "v018.db")
    applied = apply_pending(db, MIGRATIONS_DIR)
    assert "V018__turn_errors" in applied

    conn = sqlite3.connect(db)
    try:
        assert _column_names(conn, "turn_errors") == {
            "error_id", "turn_id", "session_key", "session_id", "ts_ms",
            "surface", "error_class", "message", "traceback", "provider",
            "model", "fallback_hops",
        }
        conn.execute(
            "INSERT INTO turn_errors (error_id, session_key, ts_ms) VALUES (?, ?, ?)",
            ("abcd1234", "agent:main:webchat:s1", 1_000_000),
        )
        conn.commit()
        row = conn.execute("SELECT fallback_hops FROM turn_errors").fetchone()
        assert row == (0,)
    finally:
        conn.close()


def test_v018_rollback_drops_table(tmp_path: Path) -> None:
    db = str(tmp_path / "v018-rollback.db")
    apply_pending(db, MIGRATIONS_DIR)
    backend = get_backend(f"sqlite:///{db}")
    migrations = read_migrations(str(MIGRATIONS_DIR))
    by_id = {migration.id: migration for migration in migrations}
    backend.rollback_migrations([by_id["V018__turn_errors"]])
    conn = sqlite3.connect(db)
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='turn_errors'"
        ).fetchone()
        assert row is None
    finally:
        conn.close()
