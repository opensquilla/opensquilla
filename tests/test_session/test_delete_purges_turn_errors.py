"""Session delete purges yoyo-owned turn_errors rows (router_decisions precedent)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from opensquilla.persistence.migrator import apply_pending
from opensquilla.session.models import SessionNode
from opensquilla.session.storage import SessionStorage

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


async def test_delete_session_purges_turn_errors(tmp_path) -> None:
    db = str(tmp_path / "sessions.db")
    apply_pending(db, MIGRATIONS_DIR)
    storage = SessionStorage(db)
    await storage.connect()
    try:
        await storage.upsert_session(
            SessionNode(session_key="agent:main:test:purge", session_id="sid-purge")
        )
        conn = sqlite3.connect(db)
        conn.execute(
            "INSERT INTO turn_errors (error_id, session_key, ts_ms) VALUES (?, ?, ?)",
            ("abcd1234", "agent:main:test:purge", 1_000_000),
        )
        conn.commit()
        conn.close()

        await storage.delete_session("agent:main:test:purge")

        conn = sqlite3.connect(db)
        rows = conn.execute("SELECT * FROM turn_errors").fetchall()
        conn.close()
        assert rows == []
        assert await storage.get_session("agent:main:test:purge") is None
    finally:
        await storage.close()
