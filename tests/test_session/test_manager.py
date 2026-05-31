"""Tests for SessionManager lifecycle operations."""

import contextlib
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio

from opensquilla.session.compaction import CompactionConfig
from opensquilla.session.manager import SessionManager
from opensquilla.session.models import (
    SessionContextState,
    SessionIntent,
    SessionStatus,
    SessionSummary,
    TranscriptEntry,
)
from opensquilla.session.storage import SessionStorage


@pytest_asyncio.fixture
async def manager():
    storage = SessionStorage(":memory:")
    await storage.connect()
    mgr = SessionManager(storage, inject_time_prefix=False)
    yield mgr
    await storage.close()


@pytest.mark.asyncio
async def test_create_session(manager):
    node = await manager.create("agent:main:main")
    assert node.session_key == "agent:main:main"
    assert node.status == SessionStatus.RUNNING
    assert node.session_id is not None


@pytest.mark.asyncio
async def test_get_session_returns_existing_without_touching(manager):
    node = await manager.create("agent:main:main")

    fetched = await manager.get_session("agent:main:main")
    missing = await manager.get_session("agent:main:missing")

    assert fetched is not None
    assert fetched.session_key == node.session_key
    assert fetched.session_id == node.session_id
    assert missing is None


@pytest.mark.asyncio
async def test_create_duplicate_raises(manager):
    await manager.create("agent:main:main")
    with pytest.raises(ValueError):
        await manager.create("agent:main:main")


@pytest.mark.asyncio
async def test_get_or_create_creates(manager):
    node, created = await manager.get_or_create("agent:main:main")
    assert created is True


@pytest.mark.asyncio
async def test_get_or_create_returns_existing(manager):
    await manager.create("agent:main:main")
    node, created = await manager.get_or_create("agent:main:main")
    assert created is False


@pytest.mark.asyncio
async def test_apply_intent_continue_preserves_existing_identity_and_transcript(manager):
    node = await manager.create("agent:main:main")
    await manager.append_message("agent:main:main", "user", "hello")

    applied, rotated = await manager.apply_intent("agent:main:main", SessionIntent.CONTINUE)

    assert rotated is False
    assert applied.session_id == node.session_id
    assert len(await manager.get_transcript("agent:main:main")) == 1


@pytest.mark.asyncio
async def test_apply_intent_new_chat_rejects_existing_key(manager):
    await manager.create("agent:main:main")

    with pytest.raises(ValueError, match="session_key conflict"):
        await manager.apply_intent("agent:main:main", SessionIntent.NEW_CHAT)


@pytest.mark.asyncio
async def test_apply_intent_reset_same_key_rotates_identity_and_clears_state(
    manager, tmp_path, monkeypatch
):
    monkeypatch.setenv("OPENSQUILLA_SESSION_ARCHIVE_DIR", str(tmp_path / "archives"))
    node = await manager.create("agent:main:main")
    old_session_id = node.session_id
    node.total_tokens = 123
    node.input_tokens = 10
    node.output_tokens = 20
    node.estimated_cost_usd = 0.42
    node.total_cost_usd = 0.42
    node.billed_cost_usd = 0.30
    node.estimated_cost_component_usd = 0.12
    node.cost_source = "mixed"
    node.missing_cost_entries = 1
    node.cache_read = 7
    node.cache_write = 8
    await manager._storage.upsert_session(node)
    await manager.append_message("agent:main:main", "user", "hello")
    await manager._storage.save_summary(
        SessionSummary(
            session_id=old_session_id,
            session_key="agent:main:main",
            summary_text="old summary",
        )
    )
    await manager.save_context_state(
        SessionContextState(
            session_id=old_session_id,
            session_key="agent:main:main",
            provider="portable",
            state_kind="structured_summary_v1",
            payload={"user_goal": "old task"},
            covered_through_id=1,
            valid=True,
        )
    )

    applied, rotated = await manager.apply_intent("agent:main:main", SessionIntent.RESET_SAME_KEY)

    assert rotated is True
    assert applied.session_key == "agent:main:main"
    assert applied.session_id != old_session_id
    assert await manager._storage.count_transcript_entries(old_session_id) == 0
    assert await manager._storage.count_transcript_entries(applied.session_id) == 0
    assert await manager._storage.get_all_summaries(old_session_id) == []
    assert await manager.get_context_states("agent:main:main") == []
    invalidated_states = await manager.get_context_states("agent:main:main", valid_only=False)
    assert len(invalidated_states) == 1
    assert invalidated_states[0].valid is False
    assert invalidated_states[0].invalid_reason == "session_reset"
    assert applied.total_tokens == 0
    assert applied.input_tokens == 0
    assert applied.output_tokens == 0
    assert applied.estimated_cost_usd == 0.0
    assert applied.total_cost_usd == 0.0
    assert applied.billed_cost_usd == 0.0
    assert applied.estimated_cost_component_usd == 0.0
    assert applied.cost_source == "none"
    assert applied.missing_cost_entries == 0
    assert applied.cache_read == 0
    assert applied.cache_write == 0
    archive_files = list((tmp_path / "archives").glob("*.json"))
    assert len(archive_files) == 1
    archived = json.loads(archive_files[0].read_text(encoding="utf-8"))
    assert archived["session_key"] == "agent:main:main"
    assert archived["session_id"] == old_session_id
    assert archived["transcript_entries"][0]["content"] == "hello"
    assert archived["summaries"][0]["summary_text"] == "old summary"


@pytest.mark.asyncio
async def test_reset_same_key_archive_preserves_compacted_canonical_transcript(
    manager, tmp_path, monkeypatch
):
    monkeypatch.setenv("OPENSQUILLA_SESSION_ARCHIVE_DIR", str(tmp_path / "archives"))
    node = await manager.create("agent:main:main")
    old_session_id = node.session_id
    for index in range(4):
        await manager.append_message("agent:main:main", "user", f"msg {index}", token_count=5)
    await manager.persist_compaction_result(
        "agent:main:main",
        "short summary",
        [{"role": "assistant", "content": "latest reply"}],
        compaction_id="cmp_reset_archive",
    )

    canonical_before_reset = [
        entry.content for entry in await manager.get_canonical_transcript("agent:main:main")
    ]

    applied, rotated = await manager.apply_intent("agent:main:main", SessionIntent.RESET_SAME_KEY)

    assert rotated is True
    assert applied.session_id != old_session_id
    archive_files = list((tmp_path / "archives").glob("*.json"))
    assert len(archive_files) == 1
    archived = json.loads(archive_files[0].read_text(encoding="utf-8"))
    assert [entry["content"] for entry in archived["transcript_entries"]] == (
        canonical_before_reset
    )
    assert archived["summaries"][0]["compaction_id"] == "cmp_reset_archive"


@pytest.mark.asyncio
async def test_apply_intent_reset_same_key_missing_creates_session(manager):
    applied, rotated = await manager.apply_intent(
        "agent:main:missing", SessionIntent.RESET_SAME_KEY
    )

    assert rotated is True
    assert applied.session_key == "agent:main:missing"
    assert applied.session_id


@pytest.mark.asyncio
async def test_apply_intent_reset_same_key_archive_failure_does_not_block(
    manager, tmp_path, monkeypatch
):
    archive_file = tmp_path / "not-a-directory"
    archive_file.write_text("occupied", encoding="utf-8")
    monkeypatch.setenv("OPENSQUILLA_SESSION_ARCHIVE_DIR", str(archive_file))
    node = await manager.create("agent:main:main")
    old_session_id = node.session_id
    await manager.append_message("agent:main:main", "user", "hello")

    applied, rotated = await manager.apply_intent("agent:main:main", SessionIntent.RESET_SAME_KEY)

    assert rotated is True
    assert applied.session_id != old_session_id
    assert await manager._storage.count_transcript_entries(old_session_id) == 0


@pytest.mark.asyncio
async def test_resume_touches_updated_at(manager):
    node = await manager.create("agent:main:main")
    old_ts = node.updated_at
    import asyncio

    await asyncio.sleep(0.01)
    resumed = await manager.resume("agent:main:main")
    assert resumed.updated_at >= old_ts


@pytest.mark.asyncio
async def test_resume_missing_raises(manager):
    with pytest.raises(KeyError):
        await manager.resume("agent:main:nope")


@pytest.mark.asyncio
async def test_update_fields(manager):
    await manager.create("agent:main:main")
    updated = await manager.update("agent:main:main", model="claude-opus-4-6", channel="telegram")
    assert updated.model == "claude-opus-4-6"
    assert updated.channel == "telegram"


@pytest.mark.asyncio
async def test_finish_sets_status(manager):
    await manager.create("agent:main:main")
    node = await manager.finish("agent:main:main")
    assert node.status == SessionStatus.DONE
    assert node.ended_at is not None
    assert node.runtime_ms is not None


@pytest.mark.asyncio
async def test_finish_failed(manager):
    await manager.create("agent:main:main")
    node = await manager.finish("agent:main:main", status=SessionStatus.FAILED)
    assert node.status == SessionStatus.FAILED


@pytest.mark.asyncio
async def test_append_message(manager):
    await manager.create("agent:main:main")
    entry = await manager.append_message("agent:main:main", "user", "Hello!")
    assert entry.role == "user"
    assert entry.content == "Hello!"


@pytest.mark.asyncio
async def test_append_message_updates_tokens(manager):
    await manager.create("agent:main:main")
    await manager.append_message("agent:main:main", "user", "hi", token_count=10)
    node = await manager._storage.get_session("agent:main:main")
    assert node.total_tokens == 10


@pytest.mark.asyncio
async def test_append_message_with_turn_usage_does_not_double_count_output_tokens(manager):
    await manager.create("agent:main:main")
    await manager.append_message(
        "agent:main:main",
        "assistant",
        "hi",
        turn_usage={"model": "gpt-test", "input_tokens": 10, "output_tokens": 3},
        token_count=3,
    )
    node = await manager._storage.get_session("agent:main:main")
    assert node.total_tokens == 0


@pytest.mark.asyncio
async def test_get_transcript(manager):
    await manager.create("agent:main:main")
    await manager.append_message("agent:main:main", "user", "msg1")
    await manager.append_message("agent:main:main", "assistant", "resp1")
    entries = await manager.get_transcript("agent:main:main")
    assert len(entries) == 2


@pytest.mark.asyncio
async def test_get_transcript_orders_same_timestamp_by_insert_id(manager):
    node = await manager.create("agent:main:main")
    for content in ("first", "second", "third"):
        await manager._storage.append_transcript_entry(
            TranscriptEntry(
                session_id=node.session_id,
                session_key=node.session_key,
                role="user",
                content=content,
                created_at=12345,
            )
        )

    entries = await manager.get_transcript("agent:main:main")

    assert [entry.content for entry in entries] == ["first", "second", "third"]
    assert [entry.id for entry in entries] == sorted(entry.id for entry in entries)


def test_get_transcript_query_uses_id_tiebreaker() -> None:
    source = Path("src/opensquilla/session/storage.py").read_text(encoding="utf-8")

    assert "ORDER BY created_at ASC, id ASC LIMIT ? OFFSET ?" in source


@pytest.mark.asyncio
async def test_truncate_zero_removes_all_entries(manager):
    await manager.create("agent:main:main")
    await manager.append_message("agent:main:main", "user", "msg1")
    await manager.append_message("agent:main:main", "assistant", "resp1")

    result = await manager.truncate("agent:main:main", max_messages=0)

    assert result == {"truncated": True, "before_count": 2, "after_count": 0}
    assert await manager.get_transcript("agent:main:main") == []


@pytest.mark.asyncio
async def test_branch_creates_child(manager):
    await manager.create("agent:main:main")
    child = await manager.branch("agent:main:main", "agent:main:direct:u1")
    assert child.parent_session_key == "agent:main:main"
    assert child.spawn_depth == 1


@pytest.mark.asyncio
async def test_branch_fork_transcript(manager):
    await manager.create("agent:main:main")
    await manager.append_message("agent:main:main", "user", "parent msg", token_count=5)
    await manager.append_message(
        "agent:main:main",
        "assistant",
        "parent reply",
        turn_usage={"model": "openai/gpt-test", "input_tokens": 11, "output_tokens": 5},
        token_count=5,
    )
    child = await manager.branch("agent:main:main", "agent:main:direct:u1", fork_transcript=True)
    assert child.forked_from_parent is True
    entries = await manager.get_transcript("agent:main:direct:u1")
    assert len(entries) == 2
    assert entries[0].content == "parent msg"
    assert entries[1].turn_usage == {
        "model": "openai/gpt-test",
        "input_tokens": 11,
        "output_tokens": 5,
    }


@pytest.mark.asyncio
async def test_branch_fork_transcript_copies_compaction_summaries(manager):
    parent = await manager.create("agent:main:main")
    await manager.append_message("agent:main:main", "user", "kept tail", token_count=5)
    await manager._storage.save_summary(
        SessionSummary(
            session_id=parent.session_id,
            session_key="agent:main:main",
            compaction_id="cmp_branch_1",
            trigger_reason="preflight_compaction",
            summary_text="older compacted context",
            summary_payload={"user_goal": "continue the parent task"},
            summary_format="structured_v1",
            summary_source="llm",
            coverage_status="pass",
            missing_obligations=["none"],
            critical_carry_forward=["remember file path"],
            tokens_before=1000,
            tokens_after=300,
            removed_count=3,
            kept_count=1,
            chunk_count=2,
            flush_receipt_status="safe",
            covered_through_id=123,
        )
    )
    await manager.save_context_state(
        SessionContextState(
            session_id=parent.session_id,
            session_key="agent:main:main",
            provider="portable",
            state_kind="structured_summary_v1",
            payload={"user_goal": "continue the parent task"},
            covered_through_id=123,
            portable=True,
            cacheable=True,
        )
    )

    child = await manager.branch("agent:main:main", "agent:main:direct:u1", fork_transcript=True)

    assert child.forked_from_parent is True
    child_summaries = await manager.get_summaries("agent:main:direct:u1")
    assert len(child_summaries) == 1
    assert child_summaries[0].summary_text == "older compacted context"
    assert child_summaries[0].compaction_id == "cmp_branch_1"
    assert child_summaries[0].trigger_reason == "preflight_compaction"
    assert child_summaries[0].summary_payload == {"user_goal": "continue the parent task"}
    assert child_summaries[0].summary_format == "structured_v1"
    assert child_summaries[0].summary_source == "llm"
    assert child_summaries[0].coverage_status == "pass"
    assert child_summaries[0].missing_obligations == ["none"]
    assert child_summaries[0].critical_carry_forward == ["remember file path"]
    assert child_summaries[0].tokens_before == 1000
    assert child_summaries[0].tokens_after == 300
    assert child_summaries[0].removed_count == 3
    assert child_summaries[0].kept_count == 1
    assert child_summaries[0].chunk_count == 2
    assert child_summaries[0].flush_receipt_status == "safe"
    assert child_summaries[0].covered_through_id == 123
    assert child_summaries[0].session_id == child.session_id
    assert child_summaries[0].session_key == "agent:main:direct:u1"
    child_states = await manager.get_context_states("agent:main:direct:u1")
    assert len(child_states) == 1
    assert child_states[0].session_id == child.session_id
    assert child_states[0].session_key == "agent:main:direct:u1"
    assert child_states[0].payload == {"user_goal": "continue the parent task"}
    assert child_states[0].portable is True
    assert child_states[0].cacheable is True


@pytest.mark.asyncio
async def test_branch_fork_transcript_copies_compacted_archive(manager):
    await manager.create("agent:main:main")
    for index in range(4):
        await manager.append_message("agent:main:main", "user", f"msg {index}", token_count=5)
    await manager.persist_compaction_result(
        "agent:main:main",
        "short summary",
        [{"role": "assistant", "content": "latest reply"}],
        compaction_id="cmp_branch_archive",
        trigger_reason="agent_inline_overflow",
    )
    parent_canonical = [
        entry.content for entry in await manager.get_canonical_transcript("agent:main:main")
    ]

    child = await manager.branch("agent:main:main", "agent:main:direct:u1", fork_transcript=True)

    assert child.parent_session_key == "agent:main:main"
    assert [entry.content for entry in await manager.get_transcript("agent:main:direct:u1")] == [
        "latest reply"
    ]
    assert [
        entry.content for entry in await manager.get_canonical_transcript("agent:main:direct:u1")
    ] == parent_canonical
    child_summaries = await manager.get_summaries("agent:main:direct:u1")
    assert child_summaries[0].compaction_id == "cmp_branch_archive"
    assert child_summaries[0].trigger_reason == "agent_inline_overflow"


@pytest.mark.asyncio
async def test_context_state_roundtrip_and_invalidate(manager):
    node = await manager.create("agent:main:main")
    state = await manager.save_context_state(
        SessionContextState(
            session_id=node.session_id,
            session_key="agent:main:main",
            provider="portable",
            model=None,
            state_kind="structured_summary_v1",
            payload={"current_status": "summary state"},
            covered_through_id=42,
            portable=True,
            cacheable=True,
        )
    )

    loaded = await manager.get_context_states("agent:main:main")

    assert state.id is not None
    assert len(loaded) == 1
    assert loaded[0].payload == {"current_status": "summary state"}
    assert loaded[0].portable is True
    assert loaded[0].cacheable is True
    assert loaded[0].valid is True

    invalidated = await manager.invalidate_context_states(
        "agent:main:main",
        state_kind="structured_summary_v1",
        reason="provider switched",
    )

    assert invalidated == 1
    assert await manager.get_context_states("agent:main:main") == []
    invalid = await manager.get_context_states("agent:main:main", valid_only=False)
    assert len(invalid) == 1
    assert invalid[0].valid is False
    assert invalid[0].invalid_reason == "provider switched"


@pytest.mark.asyncio
async def test_storage_migrates_legacy_summary_metadata_columns(tmp_path):
    db_path = tmp_path / "legacy.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE session_summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                session_key TEXT NOT NULL,
                compaction_index INTEGER NOT NULL DEFAULT 0,
                summary_text TEXT NOT NULL,
                covered_through_id INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL,
                schema_version INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        conn.execute(
            """
            INSERT INTO session_summaries (
                session_id, session_key, compaction_index, summary_text,
                covered_through_id, created_at, schema_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("legacy-session", "agent:main:legacy", 0, "legacy summary", 7, 123, 1),
        )

    storage = SessionStorage(str(db_path))
    await storage.connect()
    try:
        async with storage.conn.execute("PRAGMA table_info(session_summaries)") as cur:
            columns = {row[1] for row in await cur.fetchall()}
        assert {
            "compaction_id",
            "trigger_reason",
            "summary_payload",
            "summary_format",
            "summary_source",
            "coverage_status",
            "missing_obligations",
            "critical_carry_forward",
            "tokens_before",
            "tokens_after",
            "removed_count",
            "kept_count",
            "chunk_count",
            "flush_receipt_status",
        }.issubset(columns)

        summary = await storage.get_latest_summary("legacy-session")
        assert summary is not None
        assert summary.summary_text == "legacy summary"
        assert summary.summary_payload is None
        assert summary.summary_format == "text"
        assert summary.summary_source == "unknown"
        assert summary.coverage_status == "unknown"
        assert summary.missing_obligations is None
        assert summary.critical_carry_forward is None
        assert summary.compaction_id is None
        assert summary.trigger_reason is None
        assert summary.tokens_before is None
        assert summary.tokens_after is None
        assert summary.removed_count == 0
        assert summary.kept_count == 0
        assert summary.chunk_count == 0
        assert summary.flush_receipt_status == "unknown"
    finally:
        await storage.close()


@pytest.mark.asyncio
async def test_storage_migrates_session_context_state_table(tmp_path):
    db_path = tmp_path / "legacy-context-state.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE sessions (session_key TEXT PRIMARY KEY)")

    storage = SessionStorage(str(db_path))
    await storage.connect()
    try:
        async with storage.conn.execute("PRAGMA table_info(session_context_states)") as cur:
            columns = {row[1] for row in await cur.fetchall()}
        assert {
            "session_id",
            "session_key",
            "provider",
            "model",
            "state_kind",
            "payload",
            "covered_through_id",
            "created_at",
            "expires_at",
            "portable",
            "cacheable",
            "valid",
            "invalid_reason",
        }.issubset(columns)
    finally:
        await storage.close()


@pytest.mark.asyncio
async def test_branch_fork_skipped_if_over_budget(manager):
    await manager.create("agent:main:main")
    await manager.append_message("agent:main:main", "user", "msg", token_count=1000)
    child = await manager.branch(
        "agent:main:main", "agent:main:direct:u1", fork_transcript=True, max_fork_tokens=10
    )
    assert child.forked_from_parent is False


@pytest.mark.asyncio
async def test_branch_fork_budget_counts_compaction_summaries(manager):
    parent = await manager.create("agent:main:main")
    await manager.append_message("agent:main:main", "user", "kept", token_count=1)
    await manager._storage.save_summary(
        SessionSummary(
            session_id=parent.session_id,
            session_key="agent:main:main",
            summary_text="x" * 400,
        )
    )

    child = await manager.branch(
        "agent:main:main",
        "agent:main:direct:u1",
        fork_transcript=True,
        max_fork_tokens=10,
    )

    assert child.forked_from_parent is False
    assert await manager.get_transcript("agent:main:direct:u1") == []
    assert await manager.get_summaries("agent:main:direct:u1") == []


@pytest.mark.asyncio
async def test_compact_no_op_small_context(manager):
    await manager.create("agent:main:main")
    await manager.append_message("agent:main:main", "user", "hi", token_count=5)
    summary = await manager.compact("agent:main:main", context_window_tokens=100_000)
    assert summary == ""


@pytest.mark.asyncio
async def test_compact_reduces_transcript(manager):
    await manager.create("agent:main:main")
    # Add many large messages
    for i in range(20):
        await manager.append_message("agent:main:main", "user", "x" * 500, token_count=200)
    summary = await manager.compact("agent:main:main", context_window_tokens=1000)
    assert summary != ""
    node = await manager._storage.get_session("agent:main:main")
    assert node.compaction_count == 1
    transcript = await manager.get_transcript("agent:main:main")
    assert transcript
    assert all(entry.role != "system" for entry in transcript)
    summaries = await manager._storage.get_all_summaries(node.session_id)
    assert len(summaries) == 1


@pytest.mark.asyncio
async def test_compact_with_result_returns_source_and_persists(manager):
    await manager.create("agent:main:main")
    for i in range(20):
        await manager.append_message(
            "agent:main:main",
            "user",
            f"msg {i} " + ("x" * 500),
            token_count=200,
        )
    original_contents = [entry.content for entry in await manager.get_transcript("agent:main:main")]

    result = await manager.compact_with_result("agent:main:main", context_window_tokens=1000)

    assert result.summary
    assert result.summary_source == "fallback"
    node = await manager._storage.get_session("agent:main:main")
    assert node.compaction_count == 1
    transcript = await manager.get_transcript("agent:main:main")
    assert transcript
    assert all(entry.role != "system" for entry in transcript)
    summaries = await manager.get_summaries("agent:main:main")
    assert [summary.summary_text for summary in summaries] == [result.summary]
    assert summaries[0].summary_format == "structured_v1"
    assert summaries[0].summary_source == result.summary_source
    assert summaries[0].coverage_status in {"unknown", "pass", "pass_with_backfill"}
    assert summaries[0].summary_payload is not None
    assert summaries[0].summary_payload["schema_version"] == 1
    assert summaries[0].compaction_id
    assert summaries[0].tokens_before == result.tokens_before
    assert summaries[0].tokens_after == result.tokens_after
    assert summaries[0].removed_count == result.removed_count
    assert summaries[0].kept_count == len(result.kept_entries)
    assert summaries[0].chunk_count == result.chunks_processed
    canonical_contents = [
        entry.content for entry in await manager.get_canonical_transcript("agent:main:main")
    ]
    assert canonical_contents == original_contents
    assert [entry.content for entry in transcript] == original_contents[-len(transcript) :]


@pytest.mark.asyncio
async def test_compact_with_result_skips_rewrite_when_transcript_changes(manager):
    await manager.create("agent:main:main")
    for i in range(20):
        await manager.append_message(
            "agent:main:main",
            "user",
            f"msg {i} " + ("x" * 500),
            token_count=200,
        )
    original_contents = [entry.content for entry in await manager.get_transcript("agent:main:main")]
    context_entries = 0

    @contextlib.asynccontextmanager
    async def mutation_context():
        nonlocal context_entries
        context_entries += 1
        if context_entries == 2:
            await manager.append_message(
                "agent:main:main",
                "user",
                "late queued followup",
                token_count=3,
            )
        yield

    result = await manager.compact_with_result(
        "agent:main:main",
        context_window_tokens=1000,
        mutation_context=mutation_context,
    )

    assert result.summary == ""
    assert result.summary_source == "skipped"
    assert result.skip_reason == "stale_preimage"
    assert result.removed_count == 0
    node = await manager._storage.get_session("agent:main:main")
    assert node.compaction_count == 0
    assert await manager.get_summaries("agent:main:main") == []
    transcript = await manager.get_transcript("agent:main:main")
    assert [entry.content for entry in transcript] == original_contents + ["late queued followup"]


@pytest.mark.asyncio
async def test_compact_with_result_marks_unsafe_receipt_as_degraded_forensic(manager):
    await manager.create("agent:main:main")
    for i in range(20):
        await manager.append_message(
            "agent:main:main",
            "user",
            f"unsafe msg {i} " + ("x" * 500),
            token_count=200,
        )
    original_contents = [entry.content for entry in await manager.get_transcript("agent:main:main")]

    result = await manager.compact_with_result(
        "agent:main:main",
        context_window_tokens=1000,
        flush_receipt_status="unsafe",
    )

    assert result.removed_count > 0
    summaries = await manager.get_summaries("agent:main:main")
    assert summaries[0].flush_receipt_status == "degraded_forensic"
    canonical_contents = [
        entry.content for entry in await manager.get_canonical_transcript("agent:main:main")
    ]
    assert canonical_contents == original_contents


@pytest.mark.asyncio
async def test_degraded_compaction_preimage_can_be_listed_for_repair(manager):
    await manager.create("agent:main:main")
    for i in range(20):
        await manager.append_message(
            "agent:main:main",
            "user",
            f"repair msg {i} " + ("x" * 500),
            token_count=200,
        )

    await manager.compact_with_result(
        "agent:main:main",
        context_window_tokens=1000,
        flush_receipt_status="degraded_forensic",
    )

    pending = await manager.list_degraded_compactions(agent_id="main")
    assert len(pending) == 1
    assert pending[0].flush_receipt_status == "degraded_forensic"
    preimage = await manager.get_compaction_preimage(pending[0])
    assert preimage
    assert preimage[0].content.startswith("repair msg 0")
    await manager.mark_compaction_repair_status(pending[0], "repaired")
    assert await manager.list_degraded_compactions(agent_id="main") == []


@pytest.mark.asyncio
async def test_compaction_flush_status_can_be_backfilled_by_compaction_id(manager):
    await manager.create("agent:main:main")
    for i in range(20):
        await manager.append_message(
            "agent:main:main",
            "user",
            f"background flush msg {i} " + ("x" * 500),
            token_count=200,
        )

    await manager.compact_with_result(
        "agent:main:main",
        context_window_tokens=1000,
        compaction_id="cmp-bg-flush",
        flush_receipt_status="degraded_forensic",
    )

    updated = await manager.mark_compaction_flush_receipt_status(
        "agent:main:main",
        "cmp-bg-flush",
        "safe",
    )

    assert updated == 1
    summaries = await manager.get_summaries("agent:main:main")
    assert summaries[0].flush_receipt_status == "safe"
    assert await manager.list_degraded_compactions(agent_id="main") == []


@pytest.mark.asyncio
async def test_noop_memory_flush_compaction_status_does_not_enter_repair_queue(manager):
    await manager.create("agent:main:main")
    for i in range(20):
        await manager.append_message(
            "agent:main:main",
            "user",
            f"noop msg {i} " + ("x" * 500),
            token_count=200,
        )

    result = await manager.compact_with_result(
        "agent:main:main",
        context_window_tokens=1000,
        flush_receipt_status="noop_no_memory",
    )

    assert result.removed_count > 0
    summaries = await manager.get_summaries("agent:main:main")
    assert summaries[0].flush_receipt_status == "noop_no_memory"
    assert await manager.list_degraded_compactions(agent_id="main") == []


@pytest.mark.asyncio
async def test_archive_only_memory_flush_compaction_status_does_not_enter_repair_queue(manager):
    await manager.create("agent:main:main")
    for i in range(20):
        await manager.append_message(
            "agent:main:main",
            "user",
            f"archive msg {i} " + ("x" * 500),
            token_count=200,
        )

    result = await manager.compact_with_result(
        "agent:main:main",
        context_window_tokens=1000,
        flush_receipt_status="archive_only",
    )

    assert result.removed_count > 0
    summaries = await manager.get_summaries("agent:main:main")
    assert summaries[0].flush_receipt_status == "archive_only"
    assert await manager.list_degraded_compactions(agent_id="main") == []


@pytest.mark.asyncio
async def test_compact_with_result_reports_and_backfills_missing_obligations(manager):
    await manager.create("agent:main:main")
    await manager.append_message(
        "agent:main:main",
        "user",
        (
            "Goal: finish continuity work.\n"
            "Constraint: do not enable coverage blocking by default.\n"
            "Keep src/opensquilla/session/models.py and docs/Long Task Report.md."
        ),
        token_count=250,
    )
    await manager.append_message(
        "agent:main:main",
        "assistant",
        "Next I will run uv run pytest tests/test_session/test_manager.py.",
        tool_calls=[{"id": "call_exec_1", "type": "function"}],
        token_count=250,
    )
    await manager.append_message(
        "agent:main:main",
        "tool",
        (
            "Command failed: uv run pytest tests/test_session/test_manager.py\n"
            "Exit code 1\n"
            "Error: missing summary_payload column"
        ),
        tool_call_id="call_exec_1",
        token_count=250,
    )
    for i in range(8):
        await manager.append_message(
            "agent:main:main",
            "assistant",
            f"recent tail {i}",
            token_count=20,
        )

    result = await manager.compact_with_result(
        "agent:main:main",
        context_window_tokens=500,
        config=CompactionConfig(safety_margin=1.0),
    )

    assert result.removed_count > 0
    summaries = await manager.get_summaries("agent:main:main")
    summary = summaries[0]
    assert summary.summary_text == result.summary
    assert summary.summary_format == "structured_v1"
    assert summary.summary_payload is not None
    assert summary.coverage_status == "pass_with_backfill"
    assert summary.missing_obligations
    assert summary.critical_carry_forward
    assert "src/opensquilla/session/models.py" in str(summary.summary_payload)
    assert any("call_exec_1" in item for item in summary.critical_carry_forward)
    assert await manager.get_transcript("agent:main:main")


@pytest.mark.asyncio
async def test_compact_with_result_strict_coverage_blocks_destructive_rewrite(manager):
    node = await manager.create("agent:main:main")
    late_critical_path = "src/opensquilla/session/critical_continuity.py"
    await manager.append_message(
        "agent:main:main",
        "user",
        "Goal: preserve strict continuity. " + ("padding " * 40) + late_critical_path,
        token_count=650,
    )
    for index in range(4):
        await manager.append_message(
            "agent:main:main",
            "assistant",
            f"recent tail {index}",
            token_count=20,
        )
    original_transcript = await manager.get_transcript("agent:main:main")

    result = await manager.compact_with_result(
        "agent:main:main",
        context_window_tokens=300,
        config=CompactionConfig(safety_margin=1.0, coverage_blocking=True),
    )

    assert result.removed_count == 0
    assert result.skip_reason == "coverage_blocked"
    assert result.coverage_status == "fail_blocked"
    assert any(late_critical_path in item for item in result.missing_obligations or [])
    assert await manager.get_transcript("agent:main:main") == original_transcript
    assert await manager.get_summaries("agent:main:main") == []
    assert await manager.get_context_states("agent:main:main") == []
    current_node = await manager._storage.get_session("agent:main:main")
    assert current_node is not None
    assert current_node.session_id == node.session_id
    assert current_node.compaction_count == 0


@pytest.mark.asyncio
async def test_compact_with_result_writes_portable_context_state(manager):
    await manager.create("agent:main:main")
    await manager.append_message(
        "agent:main:main",
        "user",
        "Goal: keep portable state. File src/opensquilla/session/models.py.",
        token_count=250,
    )
    for i in range(8):
        await manager.append_message(
            "agent:main:main",
            "assistant",
            f"recent tail {i}",
            token_count=20,
        )

    result = await manager.compact_with_result(
        "agent:main:main",
        context_window_tokens=300,
        config=CompactionConfig(safety_margin=1.0),
    )

    states = await manager.get_context_states("agent:main:main")

    assert result.removed_count > 0
    assert len(states) == 1
    state = states[0]
    assert state.provider == "portable"
    assert state.model is None
    assert state.state_kind == "structured_summary_v1"
    summaries = await manager.get_summaries("agent:main:main")
    assert summaries[0].compaction_id
    payload_without_correlation = dict(state.payload)
    assert payload_without_correlation.pop("compaction_id") == summaries[0].compaction_id
    assert payload_without_correlation == result.summary_payload
    assert state.covered_through_id > 0
    assert state.portable is True
    assert state.cacheable is True
    assert state.valid is True
    assert await manager.get_transcript("agent:main:main")


@pytest.mark.asyncio
async def test_compact_with_result_preserves_tool_metadata_for_boundary_cut(manager):
    await manager.create("agent:main:main")
    await manager.append_message("agent:main:main", "user", "old context", token_count=30)
    await manager.append_message(
        "agent:main:main",
        "assistant",
        "calling tool",
        tool_calls=[{"id": "call_1", "type": "function"}],
        token_count=4,
    )
    await manager.append_message(
        "agent:main:main",
        "tool",
        "tool result",
        tool_call_id="call_1",
        token_count=4,
    )
    await manager.append_message("agent:main:main", "user", "next question", token_count=3)
    await manager.append_message("agent:main:main", "assistant", "answer", token_count=3)

    result = await manager.compact_with_result(
        "agent:main:main",
        context_window_tokens=50,
        config=CompactionConfig(safety_margin=1.0),
    )

    assert result.removed_count == 1
    assert result.kept_entries[0]["role"] == "assistant"
    assert result.kept_entries[0]["tool_calls"] == [{"id": "call_1", "type": "function"}]
    transcript = await manager.get_transcript("agent:main:main")
    assert transcript[0].role == "assistant"
    assert transcript[0].tool_calls == [{"id": "call_1", "type": "function"}]
    assert transcript[1].role == "tool"
    assert transcript[1].tool_call_id == "call_1"


@pytest.mark.asyncio
async def test_compact_counts_tool_calls_when_token_count_is_underreported(manager):
    await manager.create("agent:main:main")
    large_content = "x" * 5000
    await manager.append_message(
        "agent:main:main",
        "assistant",
        "small visible answer",
        tool_calls=[
            {
                "type": "tool_use",
                "tool_use_id": "write-stale",
                "name": "write_file",
                "input": {"path": "index.html", "content": large_content},
            }
        ],
        token_count=1,
    )

    result = await manager.compact_with_result(
        "agent:main:main",
        context_window_tokens=50,
        config=CompactionConfig(safety_margin=1.0),
    )

    assert result.removed_count == 1
    assert result.summary
    assert large_content not in result.summary
    node = await manager._storage.get_session("agent:main:main")
    assert node.compaction_count == 1


def _fail_next_transcript_insert(monkeypatch: pytest.MonkeyPatch, storage: SessionStorage) -> None:
    original_execute = storage.conn.execute
    failed = False

    def execute(sql: str, params: Any = ()):
        nonlocal failed
        if (
            not failed
            and isinstance(sql, str)
            and sql.lstrip().upper().startswith("INSERT INTO TRANSCRIPT_ENTRIES")
        ):
            failed = True
            raise RuntimeError("rewrite insert failed")
        return original_execute(sql, params)

    monkeypatch.setattr(storage.conn, "execute", execute)


@pytest.mark.asyncio
async def test_compact_rewrite_failure_keeps_session_state_atomic(
    manager,
    monkeypatch: pytest.MonkeyPatch,
):
    node = await manager.create("agent:main:main")
    for index in range(20):
        await manager.append_message("agent:main:main", "user", f"msg {index} " + ("x" * 500))
    original_transcript = await manager.get_transcript("agent:main:main")
    original_canonical_transcript = await manager.get_canonical_transcript("agent:main:main")
    original_summaries = await manager.get_summaries("agent:main:main")
    original_node = await manager._storage.get_session("agent:main:main")

    _fail_next_transcript_insert(monkeypatch, manager._storage)

    with pytest.raises(RuntimeError, match="rewrite insert failed"):
        await manager.compact("agent:main:main", context_window_tokens=1000)

    assert await manager.get_transcript("agent:main:main") == original_transcript
    assert (
        await manager.get_canonical_transcript("agent:main:main") == original_canonical_transcript
    )
    assert await manager.get_summaries("agent:main:main") == original_summaries
    assert await manager.get_context_states("agent:main:main") == []
    current_node = await manager._storage.get_session("agent:main:main")
    assert current_node is not None
    assert original_node is not None
    assert current_node.session_id == node.session_id
    assert current_node.compaction_count == original_node.compaction_count
    assert current_node.updated_at == original_node.updated_at


@pytest.mark.asyncio
async def test_persist_compaction_result_rewrite_failure_keeps_session_state_atomic(
    manager,
    monkeypatch: pytest.MonkeyPatch,
):
    node = await manager.create("agent:main:main")
    for index in range(4):
        await manager.append_message("agent:main:main", "user", f"msg {index}", token_count=5)
    original_transcript = await manager.get_transcript("agent:main:main")
    original_canonical_transcript = await manager.get_canonical_transcript("agent:main:main")
    original_summaries = await manager.get_summaries("agent:main:main")
    original_node = await manager._storage.get_session("agent:main:main")

    _fail_next_transcript_insert(monkeypatch, manager._storage)

    with pytest.raises(RuntimeError, match="rewrite insert failed"):
        await manager.persist_compaction_result(
            "agent:main:main",
            "short summary",
            [{"role": "assistant", "content": "latest reply"}],
        )

    assert await manager.get_transcript("agent:main:main") == original_transcript
    assert (
        await manager.get_canonical_transcript("agent:main:main") == original_canonical_transcript
    )
    assert await manager.get_summaries("agent:main:main") == original_summaries
    assert await manager.get_context_states("agent:main:main") == []
    current_node = await manager._storage.get_session("agent:main:main")
    assert current_node is not None
    assert original_node is not None
    assert current_node.session_id == node.session_id
    assert current_node.compaction_count == original_node.compaction_count
    assert current_node.updated_at == original_node.updated_at


@pytest.mark.asyncio
async def test_persist_compaction_result_stores_summary_out_of_band(manager):
    node = await manager.create("agent:main:main")
    for index in range(4):
        await manager.append_message("agent:main:main", "user", f"msg {index}", token_count=5)

    await manager.persist_compaction_result(
        "agent:main:main",
        "short summary",
        [{"role": "assistant", "content": "latest reply"}],
        compaction_id="cmp_inline_1",
        trigger_reason="agent_inline_overflow",
    )

    transcript = await manager.get_transcript("agent:main:main")
    assert all(entry.role != "system" for entry in transcript)
    assert transcript[-1].content == "latest reply"
    canonical = await manager.get_canonical_transcript("agent:main:main")
    assert [entry.content for entry in canonical] == [
        "msg 0",
        "msg 1",
        "msg 2",
        "latest reply",
    ]
    async with manager._storage.conn.execute(
        "SELECT compaction_id, compaction_index FROM compacted_transcript_entries "
        "WHERE session_id = ? ORDER BY original_entry_id ASC",
        (node.session_id,),
    ) as cur:
        archived_rows = await cur.fetchall()
    assert [(row[0], row[1]) for row in archived_rows] == [
        ("cmp_inline_1", 0),
        ("cmp_inline_1", 0),
        ("cmp_inline_1", 0),
    ]
    summaries = await manager._storage.get_all_summaries(node.session_id)
    assert len(summaries) == 1
    assert summaries[0].summary_text == "short summary"
    assert summaries[0].compaction_id == "cmp_inline_1"
    assert summaries[0].trigger_reason == "agent_inline_overflow"
    assert summaries[0].removed_count == 3
    assert summaries[0].kept_count == 1
    states = await manager.get_context_states("agent:main:main")
    assert len(states) == 1
    assert states[0].state_kind == "structured_summary_v1"
    assert states[0].payload is not None
    assert states[0].payload["compaction_id"] == "cmp_inline_1"


@pytest.mark.asyncio
async def test_delete_session_removes_compacted_transcript_archive(manager):
    node = await manager.create("agent:main:main")
    for index in range(4):
        await manager.append_message("agent:main:main", "user", f"msg {index}", token_count=5)

    await manager.persist_compaction_result(
        "agent:main:main",
        "short summary",
        [{"role": "assistant", "content": "latest reply"}],
    )
    assert len(await manager.get_canonical_transcript("agent:main:main")) == 4

    await manager._storage.delete_session("agent:main:main")

    async with manager._storage.conn.execute(
        "SELECT COUNT(*) FROM compacted_transcript_entries WHERE session_id = ?",
        (node.session_id,),
    ) as cur:
        archived_count = (await cur.fetchone())[0]
    assert archived_count == 0


@pytest.mark.asyncio
async def test_persist_compaction_result_without_summary_does_not_rewrite_transcript(manager):
    node = await manager.create("agent:main:main")
    for index in range(5):
        await manager.append_message("agent:main:main", "user", f"msg {index}", token_count=5)

    original_transcript = await manager.get_transcript("agent:main:main")
    original_node = await manager._storage.get_session("agent:main:main")

    await manager.persist_compaction_result(
        "agent:main:main",
        "",
        [{"role": "assistant", "content": "latest reply"}],
    )

    assert await manager.get_transcript("agent:main:main") == original_transcript
    assert await manager.get_summaries("agent:main:main") == []
    current_node = await manager._storage.get_session("agent:main:main")
    assert current_node is not None
    assert original_node is not None
    assert current_node.session_id == node.session_id
    assert current_node.compaction_count == original_node.compaction_count
    assert current_node.updated_at == original_node.updated_at


@pytest.mark.asyncio
async def test_prune_stale(manager):
    node = await manager.create("agent:main:main")
    # force old timestamp
    node.updated_at = 1
    await manager._storage.upsert_session(node)
    pruned = await manager.prune_stale(max_age_ms=1000)
    assert pruned == 1


@pytest.mark.asyncio
async def test_cap_entries(manager):
    for i in range(10):
        await manager.create(f"agent:main:direct:u{i}")
    deleted = await manager.cap_entries(max_entries=5)
    assert deleted == 5
    remaining = await manager._storage.count_sessions()
    assert remaining == 5


@pytest.mark.asyncio
async def test_cap_entries_cleans_related_transcript_and_summaries(manager):
    session_ids: dict[str, str] = {}
    for i in range(3):
        key = f"agent:main:direct:u{i}"
        node = await manager.create(key)
        session_ids[key] = node.session_id
        await manager._storage.append_transcript_entry(
            TranscriptEntry(
                session_id=node.session_id,
                session_key=key,
                role="user",
                content="stale",
            )
        )
        await manager._storage.save_summary(
            SessionSummary(
                session_id=node.session_id,
                session_key=key,
                summary_text="summary",
            )
        )
        await manager.save_context_state(
            SessionContextState(
                session_id=node.session_id,
                session_key=key,
                provider="portable",
                state_kind="structured_summary_v1",
                payload={"summary": "state"},
                portable=True,
                cacheable=True,
            )
        )
    deleted = await manager.cap_entries(max_entries=1)
    assert deleted == 2
    remaining = {session.session_key for session in await manager._storage.list_sessions(limit=10)}
    removed = set(session_ids) - remaining
    assert len(removed) == 2
    for key in removed:
        session_id = session_ids[key]
        assert await manager._storage.count_transcript_entries(session_id) == 0
        assert await manager._storage.get_all_summaries(session_id) == []
        assert await manager.get_context_states(key, valid_only=False) == []


@pytest.mark.asyncio
async def test_archive(manager):
    await manager.create("agent:main:main")
    await manager.archive("agent:main:main")
    node = await manager._storage.get_session("agent:main:main")
    assert node.status == SessionStatus.DONE
