"""Turn-loop error records: catch-all writes a turn_errors row and the
ErrorEvent carries the matching error_id; record failure never masks the error.

Offline: a failing provider selector forces the catch-all; storage is a temp
sqlite file with real migrations.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from opensquilla.engine.runtime import TurnRunner
from opensquilla.engine.types import ErrorEvent
from opensquilla.persistence.migrator import apply_pending
from opensquilla.persistence.turn_error_writer import open_turn_error_writer
from opensquilla.session.terminal_reply import append_error_ref
from opensquilla.tools.types import ToolContext

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


class _ExplodingSelector:
    def select(self, *args, **kwargs):
        raise RuntimeError("synthetic selector explosion")

    def __getattr__(self, name):
        raise RuntimeError("synthetic selector explosion")


def _rows(db: str) -> list[sqlite3.Row]:
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute("SELECT * FROM turn_errors").fetchall()
    finally:
        conn.close()


async def _run_collect(runner: TurnRunner, session_key: str) -> list:
    return [
        event
        async for event in runner.run(
            "hello",
            session_key=session_key,
            tool_context=ToolContext(session_key=session_key),
        )
    ]


async def test_failed_turn_writes_error_record_and_ref(tmp_path) -> None:
    db = str(tmp_path / "sessions.sqlite")
    apply_pending(db, MIGRATIONS_DIR)
    writer = open_turn_error_writer(db)
    runner = TurnRunner(provider_selector=_ExplodingSelector(), turn_error_writer=writer)
    events = await _run_collect(runner, "agent:main:test:s1")
    error_events = [event for event in events if isinstance(event, ErrorEvent)]
    assert len(error_events) == 1
    event = error_events[0]
    assert event.error_id
    assert len(event.error_id) == 8

    rows = _rows(db)
    assert len(rows) == 1
    assert rows[0]["error_id"] == event.error_id
    assert rows[0]["session_key"] == "agent:main:test:s1"
    assert rows[0]["error_class"]
    assert "synthetic selector explosion" in (rows[0]["traceback"] or "")
    writer.close()


async def test_writer_failure_does_not_mask_error(tmp_path) -> None:
    class _BrokenWriter:
        def record_error(self, record):
            raise RuntimeError("store exploded")

    runner = TurnRunner(provider_selector=_ExplodingSelector(), turn_error_writer=_BrokenWriter())
    events = await _run_collect(runner, "agent:main:test:s2")
    error_events = [event for event in events if isinstance(event, ErrorEvent)]
    assert len(error_events) == 1
    assert error_events[0].message  # original error still surfaced


async def test_no_writer_yields_error_without_ref(tmp_path) -> None:
    runner = TurnRunner(provider_selector=_ExplodingSelector())
    events = await _run_collect(runner, "agent:main:test:s3")
    error_events = [event for event in events if isinstance(event, ErrorEvent)]
    assert len(error_events) == 1
    assert error_events[0].error_id == ""


def test_append_error_ref_is_idempotent() -> None:
    base = "The task failed before it could finish."
    once = append_error_ref(base, "abcd1234")
    assert once == "The task failed before it could finish. (ref: abcd1234)"
    assert append_error_ref(once, "abcd1234") == once
    assert append_error_ref(base, None) == base
    assert append_error_ref(base, "") == base
