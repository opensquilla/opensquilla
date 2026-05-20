from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from opensquilla.session.models import SessionNode, TranscriptEntry
from opensquilla.session.storage import SessionStorage


@pytest.mark.asyncio
async def test_transcript_entry_turn_usage_round_trips() -> None:
    storage = SessionStorage(":memory:")
    await storage.connect()
    try:
        node = SessionNode(session_key="agent:main:webchat:test", session_id="sid-test")
        await storage.upsert_session(node)
        await storage.append_transcript_entry(
            TranscriptEntry(
                session_id=node.session_id,
                session_key=node.session_key,
                role="assistant",
                content="done",
                turn_usage={
                    "model": "openai/gpt-test",
                    "input_tokens": 11,
                    "output_tokens": 5,
                    "cost_usd": 0.0123,
                },
            )
        )

        entries = await storage.get_transcript(node.session_id)

        assert entries[0].turn_usage == {
            "model": "openai/gpt-test",
            "input_tokens": 11,
            "output_tokens": 5,
            "cost_usd": 0.0123,
        }
    finally:
        await storage.close()


def test_v010_adds_transcript_turn_usage_column() -> None:
    migration_path = (
        Path(__file__).resolve().parents[2]
        / "migrations"
        / "V010__transcript_turn_usage.py"
    )
    spec = importlib.util.spec_from_file_location("v010_turn_usage", migration_path)
    assert spec is not None
    assert spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    with patch("yoyo.step", lambda apply, rollback: (apply, rollback)):
        spec.loader.exec_module(migration)
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute(
            """
            CREATE TABLE transcript_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                session_key TEXT NOT NULL,
                message_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT
            )
            """
        )

        migration.apply_step(conn)
        migration.apply_step(conn)

        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(transcript_entries)")
        }
        assert "turn_usage" in columns
    finally:
        conn.close()
