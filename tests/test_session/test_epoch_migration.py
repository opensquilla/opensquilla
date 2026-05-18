"""Tests for the session epoch counter.

Covers schema migration of the ``epoch`` column, NULL-row repair on
connect, reset-increments-epoch, stale-write rejection (single + concurrent),
SCHEMA_VERSION visibility, and epoch injection into event payloads.
"""

from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio

from opensquilla.compat import aiosqlite
from opensquilla.session.models import SessionNode, TranscriptEntry
from opensquilla.session.storage import SCHEMA_VERSION, SessionStorage, StaleEpochError

# ── fixtures ────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def storage():
    s = SessionStorage(":memory:")
    await s.connect()
    yield s
    await s.close()


async def _make_session(storage: SessionStorage, key: str = "agent:main:test") -> SessionNode:
    node = SessionNode(session_key=key, session_id="sid-" + key.split(":")[-1])
    await storage.upsert_session(node)
    return node


# ── SCHEMA_VERSION constant ─────────────────────────────────────────────────


def test_schema_version_constant_visible():
    """SCHEMA_VERSION is importable and >= 2 (epoch migration bumped it)."""
    assert isinstance(SCHEMA_VERSION, int)
    assert SCHEMA_VERSION >= 2


# ── epoch column default ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_epoch_column_exists_with_default_zero(storage):
    """New databases have the epoch column defaulting to 0."""
    await _make_session(storage)
    epoch = await storage.get_epoch("agent:main:test")
    assert epoch == 0


# ── old DB migrates ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_old_db_migrates():
    """A pre-epoch database (no epoch column) is migrated transparently on connect."""
    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA journal_mode=WAL")
    # Create old-style sessions table without epoch column
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            session_key TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            created_at INTEGER NOT NULL DEFAULT 0,
            updated_at INTEGER NOT NULL DEFAULT 0,
            input_tokens INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0,
            total_tokens INTEGER NOT NULL DEFAULT 0,
            total_tokens_fresh INTEGER NOT NULL DEFAULT 0,
            estimated_cost_usd REAL NOT NULL DEFAULT 0.0,
            total_cost_usd REAL NOT NULL DEFAULT 0.0,
            billed_cost_usd REAL NOT NULL DEFAULT 0.0,
            estimated_cost_component_usd REAL NOT NULL DEFAULT 0.0,
            cost_source TEXT NOT NULL DEFAULT 'none',
            missing_cost_entries INTEGER NOT NULL DEFAULT 0,
            cache_read INTEGER NOT NULL DEFAULT 0,
            cache_write INTEGER NOT NULL DEFAULT 0,
            compaction_count INTEGER NOT NULL DEFAULT 0,
            forked_from_parent INTEGER NOT NULL DEFAULT 0,
            spawn_depth INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'running',
            chat_type TEXT NOT NULL DEFAULT 'unknown',
            fast_mode INTEGER NOT NULL DEFAULT 0,
            send_policy TEXT NOT NULL DEFAULT 'allow',
            queue_mode TEXT NOT NULL DEFAULT 'steer',
            agent_id TEXT NOT NULL DEFAULT 'main',
            schema_version INTEGER NOT NULL DEFAULT 1
        )
        """
    )
    # Insert a row without epoch
    await conn.execute(
        "INSERT INTO sessions (session_key, session_id, created_at, updated_at) "
        "VALUES (?, ?, 0, 0)",
        ("agent:main:old", "sid-old"),
    )
    await conn.commit()
    await conn.close()

    # Now open via SessionStorage — migration must add epoch column
    # We can't easily pass an existing connection, so use a temp file.
    import os
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        # Build the old-style DB on disk
        conn2 = await aiosqlite.connect(db_path)
        await conn2.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                session_key TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                created_at INTEGER NOT NULL DEFAULT 0,
                updated_at INTEGER NOT NULL DEFAULT 0,
                input_tokens INTEGER NOT NULL DEFAULT 0,
                output_tokens INTEGER NOT NULL DEFAULT 0,
                total_tokens INTEGER NOT NULL DEFAULT 0,
                total_tokens_fresh INTEGER NOT NULL DEFAULT 0,
                estimated_cost_usd REAL NOT NULL DEFAULT 0.0,
                total_cost_usd REAL NOT NULL DEFAULT 0.0,
                billed_cost_usd REAL NOT NULL DEFAULT 0.0,
                estimated_cost_component_usd REAL NOT NULL DEFAULT 0.0,
                cost_source TEXT NOT NULL DEFAULT 'none',
                missing_cost_entries INTEGER NOT NULL DEFAULT 0,
                cache_read INTEGER NOT NULL DEFAULT 0,
                cache_write INTEGER NOT NULL DEFAULT 0,
                compaction_count INTEGER NOT NULL DEFAULT 0,
                forked_from_parent INTEGER NOT NULL DEFAULT 0,
                spawn_depth INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'running',
                chat_type TEXT NOT NULL DEFAULT 'unknown',
                fast_mode INTEGER NOT NULL DEFAULT 0,
                send_policy TEXT NOT NULL DEFAULT 'allow',
                queue_mode TEXT NOT NULL DEFAULT 'steer',
                agent_id TEXT NOT NULL DEFAULT 'main',
                schema_version INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        await conn2.execute(
            "INSERT INTO sessions (session_key, session_id, created_at, updated_at) "
            "VALUES (?, ?, 0, 0)",
            ("agent:main:old", "sid-old"),
        )
        await conn2.commit()
        await conn2.close()

        # Open with SessionStorage — triggers migration
        s = SessionStorage(db_path)
        await s.connect()
        try:
            # epoch column must exist and default to 0
            epoch = await s.get_epoch("agent:main:old")
            assert epoch == 0, f"Expected 0, got {epoch}"
        finally:
            await s.close()
    finally:
        os.unlink(db_path)


# ── reset increments epoch ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reset_increments_epoch(storage):
    """increment_epoch raises epoch by 1 on each call."""
    await _make_session(storage)
    key = "agent:main:test"

    assert await storage.get_epoch(key) == 0

    e1 = await storage.increment_epoch(key)
    assert e1 == 1

    e2 = await storage.increment_epoch(key)
    assert e2 == 2

    e3 = await storage.increment_epoch(key)
    assert e3 == 3


# ── startup NULL-row guard ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_null_epoch_rows_zeroed_on_connect():
    """If a row somehow has NULL epoch, _migrate_epoch_column zeros it."""
    import os
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        # Build a DB that already has the epoch column but with a NULL value
        conn = await aiosqlite.connect(db_path)
        await conn.execute(
            """
            CREATE TABLE sessions (
                session_key TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                created_at INTEGER NOT NULL DEFAULT 0,
                updated_at INTEGER NOT NULL DEFAULT 0,
                input_tokens INTEGER NOT NULL DEFAULT 0,
                output_tokens INTEGER NOT NULL DEFAULT 0,
                total_tokens INTEGER NOT NULL DEFAULT 0,
                total_tokens_fresh INTEGER NOT NULL DEFAULT 0,
                estimated_cost_usd REAL NOT NULL DEFAULT 0.0,
                total_cost_usd REAL NOT NULL DEFAULT 0.0,
                billed_cost_usd REAL NOT NULL DEFAULT 0.0,
                estimated_cost_component_usd REAL NOT NULL DEFAULT 0.0,
                cost_source TEXT NOT NULL DEFAULT 'none',
                missing_cost_entries INTEGER NOT NULL DEFAULT 0,
                cache_read INTEGER NOT NULL DEFAULT 0,
                cache_write INTEGER NOT NULL DEFAULT 0,
                compaction_count INTEGER NOT NULL DEFAULT 0,
                forked_from_parent INTEGER NOT NULL DEFAULT 0,
                spawn_depth INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'running',
                chat_type TEXT NOT NULL DEFAULT 'unknown',
                fast_mode INTEGER NOT NULL DEFAULT 0,
                send_policy TEXT NOT NULL DEFAULT 'allow',
                queue_mode TEXT NOT NULL DEFAULT 'steer',
                agent_id TEXT NOT NULL DEFAULT 'main',
                schema_version INTEGER NOT NULL DEFAULT 1,
                epoch INTEGER
            )
            """
        )
        # Insert with explicit NULL epoch
        await conn.execute(
            "INSERT INTO sessions (session_key, session_id, created_at, updated_at, epoch) "
            "VALUES (?, ?, 0, 0, NULL)",
            ("agent:main:nullrow", "sid-null"),
        )
        await conn.commit()
        await conn.close()

        s = SessionStorage(db_path)
        await s.connect()
        try:
            epoch = await s.get_epoch("agent:main:nullrow")
            assert epoch == 0
        finally:
            await s.close()
    finally:
        os.unlink(db_path)


# ── stale write rejected ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stale_write_rejected(storage):
    """A write using a stale epoch (pre-reset) returns 0 rows affected.

    Simulates a write that targets epoch=0 but the session has been reset
    (epoch=1). The WHERE epoch = ? clause must match 0 rows.
    """
    await _make_session(storage)
    key = "agent:main:test"

    # Advance epoch to 1 (one reset)
    await storage.increment_epoch(key)
    current_epoch = await storage.get_epoch(key)
    assert current_epoch == 1

    # Simulate a stale write: writer holds old_epoch=0 but session is at 1.
    old_epoch = 0
    async with storage.conn.execute(
        "UPDATE sessions SET status = 'done' WHERE session_key = ? AND epoch = ?",
        (key, old_epoch),
    ) as cur:
        rows_affected = cur.rowcount

    assert rows_affected == 0, "Stale write must not modify rows"

    # Session status must remain unchanged
    node = await storage.get_session(key)
    assert node is not None
    assert node.status == "running"


# ── concurrent stale writes all rejected ────────────────────────────────────


@pytest.mark.asyncio
async def test_concurrent_stale_writes_all_rejected(storage):
    """Three concurrent append_transcript_entry calls with stale epoch are all rejected.

    Models: turn A, B, C are in-flight capturing epoch=0; a reset fires (epoch→1);
    all three must raise StaleEpochError via the real storage write path.
    """
    node = await _make_session(storage)
    key = "agent:main:test"

    # Snapshot the epoch all three in-flight writers captured
    captured_epoch = await storage.get_epoch(key)  # 0

    # A reset fires — epoch is now 1
    await storage.increment_epoch(key)
    post_reset_epoch = await storage.get_epoch(key)
    assert post_reset_epoch == 1

    def _make_entry(label: str) -> TranscriptEntry:
        return TranscriptEntry(
            session_id=node.session_id,
            session_key=key,
            role="assistant",
            content=f"stale content from {label}",
        )

    async def _stale_write(label: str) -> bool:
        """Returns True if StaleEpochError was raised (write correctly rejected)."""
        try:
            await storage.append_transcript_entry(
                _make_entry(label), expected_epoch=captured_epoch
            )
            return False  # write was NOT rejected — bad
        except StaleEpochError:
            return True  # correctly rejected

    results = await asyncio.gather(
        _stale_write("write-A"),
        _stale_write("write-B"),
        _stale_write("write-C"),
    )

    assert results == [True, True, True], (
        f"All stale writes must be rejected; got {results}"
    )

    # No transcript entries must have been written
    entries = await storage.get_transcript(node.session_id)
    assert entries == [], f"No stale entries should persist; got {entries}"


# ── epoch in event payload ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_epoch_in_event_payload(storage):
    """emit_to_session_subscribers injects 'epoch' into session.event.* payloads.

    Uses a minimal fake ctx with real SessionStorage so that get_epoch()
    returns the live value and confirms it appears in the payload sent to
    the WS connection.
    """
    from types import SimpleNamespace

    from opensquilla.gateway.rpc_session_events import emit_to_session_subscribers

    node = await _make_session(storage)
    key = node.session_key

    # Advance epoch to 3 so we can assert the injected value is non-zero.
    for _ in range(3):
        await storage.increment_epoch(key)
    expected_epoch = await storage.get_epoch(key)
    assert expected_epoch == 3

    # Capture sent payloads via a fake connection.
    sent: list[tuple[str, dict]] = []

    class FakeConn:
        async def send_event(self, event_name: str, payload: dict) -> None:
            sent.append((event_name, payload))

    fake_conn = FakeConn()

    class FakeRegistry:
        def get(self, conn_id: str):
            return fake_conn

    class FakeSubMgr:
        def get_message_subscribers(self, session_key: str):
            return {"conn-1"}

        def get_session_subscribers(self):
            return set()

    class FakeSessionMgr:
        _storage = storage

    fake_ctx = SimpleNamespace(
        subscription_manager=FakeSubMgr(),
        session_manager=FakeSessionMgr(),
    )

    import opensquilla.gateway.websocket as _ws_module
    original_get_registry = _ws_module.get_registry

    def _patched_registry():
        return FakeRegistry()

    _ws_module.get_registry = _patched_registry
    try:
        await emit_to_session_subscribers(
            fake_ctx, key, "session.event.text_delta", {"text": "hello"}
        )
    finally:
        _ws_module.get_registry = original_get_registry

    assert sent, "Expected at least one event to be delivered"
    _event_name, payload = sent[0]
    assert "epoch" in payload, f"epoch must be injected into payload; got {payload}"
    assert payload["epoch"] == expected_epoch, (
        f"epoch in payload ({payload['epoch']}) must match storage epoch ({expected_epoch})"
    )
