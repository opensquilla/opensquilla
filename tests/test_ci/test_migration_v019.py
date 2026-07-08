"""V019 migration: durable per-turn error records (turn_errors)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from yoyo import get_backend, read_migrations

from opensquilla.persistence.migrator import apply_pending

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def test_v019_creates_turn_errors_table(tmp_path: Path) -> None:
    db = str(tmp_path / "v019.db")
    applied = apply_pending(db, MIGRATIONS_DIR)
    assert "V019__turn_errors" in applied

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


def _index_exists(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index'"
        " AND name='idx_turn_errors_session_ts'"
    ).fetchone()
    return row is not None


def test_v019_creates_index(tmp_path: Path) -> None:
    db = str(tmp_path / "v019-index.db")
    apply_pending(db, MIGRATIONS_DIR)
    conn = sqlite3.connect(db)
    try:
        assert _index_exists(conn)
    finally:
        conn.close()


def _migration_constant(name: str) -> str:
    """Extract a module-level string constant from the V019 migration source.

    The migration module cannot be imported directly (yoyo's ``step()``
    requires a live migration collector at module-exec time), so read the DDL
    constant out of the AST instead — no drift from an inline copy.
    """
    import ast

    source = (MIGRATIONS_DIR / "V019__turn_errors.py").read_text(encoding="utf-8")
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    value = ast.literal_eval(node.value)
                    assert isinstance(value, str)
                    return value
    raise AssertionError(f"constant {name!r} not found in V019 migration")


def test_v019_preexisting_table_gains_index(tmp_path: Path) -> None:
    """A turn_errors table created out-of-band still gains the index on apply."""
    db_path = tmp_path / "v019-preexisting.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(_migration_constant("CREATE_TURN_ERRORS"))
    conn.commit()
    conn.close()

    apply_pending(str(db_path), MIGRATIONS_DIR)

    conn = sqlite3.connect(str(db_path))
    try:
        assert _index_exists(conn)
    finally:
        conn.close()


def test_v019_rollback_drops_table(tmp_path: Path) -> None:
    db = str(tmp_path / "v019-rollback.db")
    apply_pending(db, MIGRATIONS_DIR)
    backend = get_backend(f"sqlite:///{db}")
    migrations = read_migrations(str(MIGRATIONS_DIR))
    by_id = {migration.id: migration for migration in migrations}
    backend.rollback_migrations([by_id["V019__turn_errors"]])
    conn = sqlite3.connect(db)
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='turn_errors'"
        ).fetchone()
        assert row is None
    finally:
        conn.close()
