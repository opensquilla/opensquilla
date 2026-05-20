"""Tests for SessionManager lifecycle operations."""

import json
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio

from opensquilla.session.compaction import CompactionConfig
from opensquilla.session.manager import SessionManager
from opensquilla.session.models import SessionIntent, SessionStatus, SessionSummary, TranscriptEntry
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

    applied, rotated = await manager.apply_intent(
        "agent:main:main", SessionIntent.RESET_SAME_KEY
    )

    assert rotated is True
    assert applied.session_key == "agent:main:main"
    assert applied.session_id != old_session_id
    assert await manager._storage.count_transcript_entries(old_session_id) == 0
    assert await manager._storage.count_transcript_entries(applied.session_id) == 0
    assert await manager._storage.get_all_summaries(old_session_id) == []
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

    applied, rotated = await manager.apply_intent(
        "agent:main:main", SessionIntent.RESET_SAME_KEY
    )

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
            summary_text="older compacted context",
            covered_through_id=123,
        )
    )

    child = await manager.branch("agent:main:main", "agent:main:direct:u1", fork_transcript=True)

    assert child.forked_from_parent is True
    child_summaries = await manager.get_summaries("agent:main:direct:u1")
    assert len(child_summaries) == 1
    assert child_summaries[0].summary_text == "older compacted context"
    assert child_summaries[0].covered_through_id == 123
    assert child_summaries[0].session_id == child.session_id
    assert child_summaries[0].session_key == "agent:main:direct:u1"


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
        await manager.append_message("agent:main:main", "user", "x" * 500, token_count=200)

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
    original_summaries = await manager.get_summaries("agent:main:main")
    original_node = await manager._storage.get_session("agent:main:main")

    _fail_next_transcript_insert(monkeypatch, manager._storage)

    with pytest.raises(RuntimeError, match="rewrite insert failed"):
        await manager.compact("agent:main:main", context_window_tokens=1000)

    assert await manager.get_transcript("agent:main:main") == original_transcript
    assert await manager.get_summaries("agent:main:main") == original_summaries
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
    assert await manager.get_summaries("agent:main:main") == original_summaries
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
    )

    transcript = await manager.get_transcript("agent:main:main")
    assert all(entry.role != "system" for entry in transcript)
    assert transcript[-1].content == "latest reply"
    summaries = await manager._storage.get_all_summaries(node.session_id)
    assert len(summaries) == 1
    assert summaries[0].summary_text == "short summary"


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
    deleted = await manager.cap_entries(max_entries=1)
    assert deleted == 2
    remaining = {session.session_key for session in await manager._storage.list_sessions(limit=10)}
    removed = set(session_ids) - remaining
    assert len(removed) == 2
    for key in removed:
        session_id = session_ids[key]
        assert await manager._storage.count_transcript_entries(session_id) == 0
        assert await manager._storage.get_all_summaries(session_id) == []


@pytest.mark.asyncio
async def test_archive(manager):
    await manager.create("agent:main:main")
    await manager.archive("agent:main:main")
    node = await manager._storage.get_session("agent:main:main")
    assert node.status == SessionStatus.DONE
