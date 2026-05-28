from __future__ import annotations

import asyncio
import logging
import time
from types import SimpleNamespace
from typing import Any, cast

import pytest

from opensquilla.engine import Agent, AgentConfig
from opensquilla.memory.embedding import NullEmbeddingProvider
from opensquilla.memory.flush import resolve_flush_plan
from opensquilla.memory.protocols import MemoryToolHandler
from opensquilla.memory.retrieval import MemoryRetriever
from opensquilla.memory.session_flush import FlushReceipt, SessionFlushService
from opensquilla.memory.store import LongTermMemoryStore
from opensquilla.memory.sync_manager import MemorySyncManager
from opensquilla.memory.types import MemorySearchOpts, SearchIntent
from opensquilla.provider import Message
from opensquilla.tool_boundary import ToolCall, ToolResult


def test_memory_tool_handler_protocol_uses_tool_boundary_types() -> None:
    async def handler(call: ToolCall) -> ToolResult:
        return ToolResult(
            tool_use_id=call.tool_use_id,
            tool_name=call.tool_name,
            content="ok",
        )

    typed_handler: MemoryToolHandler = handler

    assert typed_handler is handler


def test_resolve_flush_plan_rotates_oversized_daily_archive(tmp_path) -> None:
    first = resolve_flush_plan(workspace_dir=tmp_path, archive_max_bytes=5)
    first_path = tmp_path / first.relative_path
    first_path.parent.mkdir(parents=True)
    first_path.write_text("123456", encoding="utf-8")

    second = resolve_flush_plan(workspace_dir=tmp_path, archive_max_bytes=5)
    assert second.relative_path.endswith("-part001.md")
    second_path = tmp_path / second.relative_path
    second_path.write_text("123456", encoding="utf-8")

    third = resolve_flush_plan(workspace_dir=tmp_path, archive_max_bytes=5)
    assert third.relative_path.endswith("-part002.md")


@pytest.mark.asyncio
async def test_curated_flush_memory_is_searchable_but_raw_fallback_is_not(tmp_path) -> None:
    workspace = tmp_path / "agent"
    memory_dir = workspace / "memory"
    raw_dir = memory_dir / ".raw_fallbacks"
    raw_dir.mkdir(parents=True)
    (memory_dir / "2026-05-14-session.md").write_text(
        "Flush summary: zebra77 project decision\n",
        encoding="utf-8",
    )
    (raw_dir / "raw.md").write_text(
        "Raw fallback transcript: zebra77 should not be searched\n",
        encoding="utf-8",
    )
    store = LongTermMemoryStore(
        str(tmp_path / "memory.db"),
        embedding_provider=NullEmbeddingProvider(),
    )
    await store.initialize()
    try:
        sync = MemorySyncManager(store=store, workspace_dir=workspace, memory_dir=memory_dir)
        await sync.sync(reason="manual")
        retriever = MemoryRetriever(store)

        results = await retriever.search(
            "zebra77",
            MemorySearchOpts(max_results=5, min_score=0.0),
            intent=SearchIntent.TOOL,
        )

        paths = [result.path for result in results]
        assert "memory/2026-05-14-session.md" in paths
        assert all(".raw_fallbacks" not in path for path in paths)
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_agent_memory_flush_timeout_enters_backoff_without_retrigger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import opensquilla.engine.agent as agent_module

    async def fake_compact_context(_request):
        return SimpleNamespace(
            removed_count=0,
            summary="",
            kept_entries=[{"role": "user", "content": "hello"}],
        )

    monkeypatch.setattr(agent_module, "compact_context", fake_compact_context)

    agent = Agent(
        provider=None,  # type: ignore[arg-type]
        config=AgentConfig(
            context_window_tokens=100,
            context_overflow_threshold=0.5,
            flush_timeout_seconds=0.01,
            flush_backoff_initial_seconds=10.0,
            flush_backoff_max_seconds=20.0,
        ),
    )
    calls = 0

    async def slow_flush(_plan, _messages):
        nonlocal calls
        calls += 1
        await asyncio.sleep(1)

    monkeypatch.setattr(agent, "_run_flush", slow_flush)
    messages = [Message(role="user", content="hello")]

    try:
        await agent._check_context_overflow(messages, 60)
        first_backoff_until = agent._flush_backoff_until
        await agent._check_context_overflow(messages, 60)
    finally:
        task = agent._active_flush_task
        if task is not None and not task.done():
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    assert calls == 1
    assert first_backoff_until > time.monotonic()
    assert agent._flush_backoff_seconds == 10.0


@pytest.mark.asyncio
async def test_agent_memory_flush_timeout_records_backoff_and_compacts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import opensquilla.engine.agent as agent_module

    async def fake_compact_context(_request):
        return SimpleNamespace(
            removed_count=1,
            summary="User asked for memory flush timeout recovery.",
            kept_entries=[{"role": "user", "content": "latest turn"}],
        )

    monkeypatch.setattr(agent_module, "compact_context", fake_compact_context)

    agent = Agent(
        provider=None,  # type: ignore[arg-type]
        config=AgentConfig(
            context_window_tokens=100,
            context_overflow_threshold=0.5,
            flush_timeout_seconds=0.01,
            flush_backoff_initial_seconds=10.0,
            flush_backoff_max_seconds=20.0,
        ),
    )
    calls = 0

    async def slow_flush(_plan, _messages):
        nonlocal calls
        calls += 1
        await asyncio.sleep(1)

    monkeypatch.setattr(agent, "_run_flush", slow_flush)
    messages = [
        Message(role="user", content="older turn"),
        Message(role="assistant", content="older answer"),
        Message(role="user", content="latest turn"),
    ]

    try:
        outcome = await agent._check_context_overflow(messages, 60)
    finally:
        task = agent._active_flush_task
        if task is not None and not task.done():
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    assert outcome is not None
    assert outcome.compacted is True
    assert outcome.summary == "User asked for memory flush timeout recovery."
    assert calls == 1
    assert agent._flush_backoff_seconds == 10.0
    assert agent._last_compaction_refusal_reason is None


@pytest.mark.asyncio
async def test_agent_memory_flush_service_uses_background_timeout() -> None:
    class RecordingFlushService:
        def __init__(self) -> None:
            self.kwargs: dict[str, Any] | None = None

        async def execute(self, *_args, **kwargs):
            self.kwargs = kwargs
            return FlushReceipt(
                mode="llm",
                flushed_paths=["memory/ok.md"],
                slug="ok",
                message_count=1,
                duration_ms=1,
                raw_reason=None,
                error=None,
                indexed_chunk_count=1,
                integrity_status="ok",
                output_coverage_status="ok",
                obligation_status="ok",
            )

    service = RecordingFlushService()
    agent = Agent(
        provider=None,  # type: ignore[arg-type]
        config=AgentConfig(flush_timeout_seconds=0.01, flush_background_timeout_seconds=42.0),
        session_flush_service=service,
        session_key="agent:main:webchat:s1",
    )

    await agent._run_flush(SimpleNamespace(relative_path="memory/2026-05-14.md"), [])

    assert service.kwargs is not None
    assert service.kwargs["timeout"] == 42.0


@pytest.mark.asyncio
async def test_agent_memory_flush_raw_receipt_keeps_backoff() -> None:
    agent = Agent(
        provider=None,  # type: ignore[arg-type]
        config=AgentConfig(
            flush_backoff_initial_seconds=10.0,
            flush_backoff_max_seconds=20.0,
        ),
        session_key="agent:main:webchat:s1",
    )

    class RawFlushService:
        async def execute(self, *_args, **_kwargs) -> FlushReceipt:
            return FlushReceipt(
                mode="raw",
                flushed_paths=["memory/.raw_fallbacks/raw.md"],
                slug=None,
                message_count=1,
                duration_ms=1,
                raw_reason="timeout",
                error=None,
            )

    cast(Any, agent)._session_flush_service = RawFlushService()
    task = asyncio.create_task(
        agent._run_flush(SimpleNamespace(relative_path="memory/2026-05-14.md"), [])
    )
    agent._active_flush_task = task
    await task

    agent._mark_flush_task_completed(task)

    assert agent._flush_backoff_until > time.monotonic()
    assert agent._flush_backoff_seconds == 10.0


@pytest.mark.asyncio
async def test_agent_memory_flush_noop_llm_receipt_clears_backoff() -> None:
    agent = Agent(
        provider=None,  # type: ignore[arg-type]
        config=AgentConfig(
            flush_backoff_initial_seconds=10.0,
            flush_backoff_max_seconds=20.0,
        ),
        session_key="agent:main:webchat:s1",
    )

    async def noop_flush() -> FlushReceipt:
        return FlushReceipt(
            mode="llm",
            flushed_paths=[],
            slug="no-memory",
            message_count=1,
            duration_ms=1,
            raw_reason=None,
            error=None,
            result_status="ok_noop_no_memory",
        )

    agent._flush_backoff_until = time.monotonic() + 10.0
    agent._flush_backoff_seconds = 10.0
    task = asyncio.create_task(noop_flush())
    agent._active_flush_task = task
    await task

    agent._mark_flush_task_completed(task)

    assert agent._flush_backoff_until == 0.0
    assert agent._flush_backoff_seconds == 0.0


@pytest.mark.asyncio
async def test_agent_memory_flush_unsafe_llm_receipt_keeps_backoff() -> None:
    agent = Agent(
        provider=None,  # type: ignore[arg-type]
        config=AgentConfig(
            flush_backoff_initial_seconds=10.0,
            flush_backoff_max_seconds=20.0,
        ),
        session_key="agent:main:webchat:s1",
    )

    async def unsafe_flush() -> SimpleNamespace:
        return SimpleNamespace(
            mode="llm",
            indexed_chunk_count=1,
            integrity_status="degraded",
            output_coverage_status="ok",
            invalid_candidate_count=0,
            candidate_missing_ids=[],
            obligation_status="ok",
            obligation_missing_ids=[],
        )

    task = asyncio.create_task(unsafe_flush())
    agent._active_flush_task = task
    await task

    agent._mark_flush_task_completed(task)

    assert agent._flush_backoff_until > time.monotonic()
    assert agent._flush_backoff_seconds == 10.0


@pytest.mark.asyncio
async def test_session_flush_raw_fallback_deduplicates_same_transcript() -> None:
    calls: list[ToolCall] = []

    async def handler(call: ToolCall) -> ToolResult:
        calls.append(call)
        return ToolResult(
            tool_use_id=call.tool_use_id,
            tool_name=call.tool_name,
            content="Saved to memory/.raw_fallbacks/raw.md (0 chunks indexed).",
        )

    service = SessionFlushService(
        provider_selector=lambda _agent_id: None,
        tool_registry=SimpleNamespace(to_tool_definitions=lambda: []),
        tool_handler=handler,
    )
    messages = [Message(role="user", content="same transcript")]

    first = await service._raw_dump_fallback(
        messages,
        reason="timeout",
        agent_id="main",
        session_key="agent:main:webchat:s1",
    )
    second = await service._raw_dump_fallback(
        messages,
        reason="timeout",
        agent_id="main",
        session_key="agent:main:webchat:s1",
    )

    assert len(calls) == 1
    assert second.flushed_paths == first.flushed_paths
    assert second.raw_reason == "timeout"


@pytest.mark.asyncio
async def test_session_flush_empty_candidates_is_successful_noop_without_raw_fallback(
    caplog,
) -> None:
    class NoopProvider:
        async def complete(self, **_kwargs: Any) -> SimpleNamespace:
            return SimpleNamespace(
                content=(
                    '{"slug":"no-memory","candidates":[],'
                    '"noop_reason":"No stable long-term memory was found."}'
                )
            )

    calls: list[ToolCall] = []

    async def handler(call: ToolCall) -> ToolResult:
        calls.append(call)
        return ToolResult(
            tool_use_id=call.tool_use_id,
            tool_name=call.tool_name,
            content="Saved to memory/.raw_fallbacks/raw.md (0 chunks indexed).",
        )

    service = SessionFlushService(
        provider_selector=lambda _agent_id: NoopProvider(),
        tool_registry=SimpleNamespace(
            to_tool_definitions=lambda: [SimpleNamespace(name="memory_save")]
        ),
        tool_handler=handler,
    )
    caplog.set_level(logging.WARNING, logger="opensquilla.memory.session_flush")

    receipt = await service.execute(
        [Message(role="user", content="Please run a temporary shell command.")],
        "agent:main:webchat:s1",
        agent_id="main",
    )

    assert receipt.mode == "llm"
    assert receipt.result_status == "ok_noop_no_memory"
    assert receipt.flushed_paths == []
    assert receipt.raw_reason is None
    assert receipt.error is None
    assert receipt.indexed_chunk_count == 0
    assert calls == []
    assert all(record.getMessage() != "session_flush.llm_failed" for record in caplog.records)


@pytest.mark.asyncio
async def test_session_flush_invalid_json_records_parse_failed_archive_status() -> None:
    class InvalidJsonProvider:
        async def complete(self, **_kwargs: Any) -> SimpleNamespace:
            return SimpleNamespace(content='{"candidates": [')

    async def handler(call: ToolCall) -> ToolResult:
        return ToolResult(
            tool_use_id=call.tool_use_id,
            tool_name=call.tool_name,
            content="Saved to memory/.raw_fallbacks/raw.md (0 chunks indexed).",
        )

    receipt_rows: list[dict[str, Any]] = []

    async def receipt_writer(_receipt: FlushReceipt, **row: Any) -> None:
        receipt_rows.append(row)

    service = SessionFlushService(
        provider_selector=lambda _agent_id: InvalidJsonProvider(),
        tool_registry=SimpleNamespace(
            to_tool_definitions=lambda: [SimpleNamespace(name="memory_save")]
        ),
        tool_handler=handler,
        receipt_writer=receipt_writer,
    )

    receipt = await service.execute(
        [Message(role="user", content="temporary transcript")],
        "agent:main:webchat:s1",
        agent_id="main",
    )

    assert receipt.mode == "raw"
    assert receipt.raw_reason == "llm_error"
    assert receipt.result_status == "parse_failed_archived"
    assert len(receipt_rows) == 1
    assert {"content_hash", "source_path", "turn_id", "session_id"} <= set(
        receipt_rows[0]
    )
    assert receipt_rows[0]["scope"] == "repair"
    assert receipt_rows[0]["status"] == "repair_pending"
    assert receipt_rows[0]["reason"] == "parse_failed_archived"
    assert receipt_rows[0]["target_path"] == receipt.flushed_paths[0]
    assert receipt_rows[0]["turn_id"] == "flush:1-1"
    assert receipt_rows[0]["content_hash"] == receipt.content_hash


@pytest.mark.asyncio
async def test_session_flush_provider_exception_records_provider_failed_archive_status() -> None:
    class FailingProvider:
        async def complete(self, **_kwargs: Any) -> SimpleNamespace:
            raise RuntimeError("provider unavailable")

    async def handler(call: ToolCall) -> ToolResult:
        return ToolResult(
            tool_use_id=call.tool_use_id,
            tool_name=call.tool_name,
            content="Saved to memory/.raw_fallbacks/raw.md (0 chunks indexed).",
        )

    receipt_rows: list[dict[str, Any]] = []

    async def receipt_writer(_receipt: FlushReceipt, **row: Any) -> None:
        receipt_rows.append(row)

    service = SessionFlushService(
        provider_selector=lambda _agent_id: FailingProvider(),
        tool_registry=SimpleNamespace(
            to_tool_definitions=lambda: [SimpleNamespace(name="memory_save")]
        ),
        tool_handler=handler,
        receipt_writer=receipt_writer,
    )

    receipt = await service.execute(
        [Message(role="user", content="temporary transcript")],
        "agent:main:webchat:s1",
        agent_id="main",
    )

    assert receipt.mode == "raw"
    assert receipt.raw_reason == "llm_error"
    assert receipt.result_status == "provider_failed_archived"
    assert len(receipt_rows) == 1
    assert receipt_rows[0]["scope"] == "repair"
    assert receipt_rows[0]["status"] == "repair_pending"
    assert receipt_rows[0]["reason"] == "provider_failed_archived"
    assert receipt_rows[0]["target_path"] == receipt.flushed_paths[0]
    assert receipt_rows[0]["content_hash"] == receipt.content_hash


@pytest.mark.asyncio
async def test_session_flush_successful_llm_flush_records_flush_appended() -> None:
    async def handler(call: ToolCall) -> ToolResult:
        return ToolResult(
            tool_use_id=call.tool_use_id,
            tool_name=call.tool_name,
            content="Saved to memory/session.md (1 chunks indexed; integrity=ok).",
        )

    receipt_rows: list[dict[str, Any]] = []

    async def receipt_writer(_receipt: FlushReceipt, **row: Any) -> None:
        receipt_rows.append(row)

    service = SessionFlushService(
        provider_selector=lambda _agent_id: object(),
        tool_registry=SimpleNamespace(
            to_tool_definitions=lambda: [SimpleNamespace(name="memory_save")]
        ),
        tool_handler=handler,
        receipt_writer=receipt_writer,
    )

    async def safe_llm_flush(*_args: Any, **_kwargs: Any) -> FlushReceipt:
        return FlushReceipt(
            mode="llm",
            flushed_paths=["memory/session.md"],
            slug="session",
            message_count=1,
            duration_ms=1,
            raw_reason=None,
            error=None,
            result_status="ok_candidates_written",
            integrity_status="ok",
            indexed_chunk_count=1,
            output_coverage_status="ok",
            invalid_candidate_count=0,
            candidate_missing_ids=[],
            obligation_status="ok",
            obligation_missing_ids=[],
        )

    service._llm_flush = safe_llm_flush  # type: ignore[method-assign]

    receipt = await service.execute(
        [Message(role="user", content="remember this durable fact")],
        "agent:main:webchat:s1",
        agent_id="main",
    )

    assert receipt.result_status == "ok_candidates_written"
    assert len(receipt_rows) == 1
    assert receipt_rows[0]["scope"] == "flush"
    assert receipt_rows[0]["status"] == "flush_appended"
    assert receipt_rows[0]["reason"] is None
    assert receipt_rows[0]["target_path"] == "memory/session.md"
    assert receipt_rows[0]["turn_id"] == "flush:1-1"
    assert receipt_rows[0]["content_hash"] == receipt.content_hash


@pytest.mark.asyncio
async def test_session_flush_raw_fallback_tool_error_returns_error_receipt() -> None:
    calls: list[ToolCall] = []

    async def handler(call: ToolCall) -> ToolResult:
        calls.append(call)
        return ToolResult(
            tool_use_id=call.tool_use_id,
            tool_name=call.tool_name,
            content="disk full",
            is_error=True,
        )

    receipt_rows: list[dict[str, Any]] = []

    async def receipt_writer(_receipt: FlushReceipt, **row: Any) -> None:
        receipt_rows.append(row)

    service = SessionFlushService(
        provider_selector=lambda _agent_id: None,
        tool_registry=SimpleNamespace(to_tool_definitions=lambda: []),
        tool_handler=handler,
        receipt_writer=receipt_writer,
    )
    messages = [Message(role="user", content="same transcript")]

    first = await service._raw_dump_fallback(
        messages,
        reason="timeout",
        agent_id="main",
        session_key="agent:main:webchat:s1",
    )
    second = await service._raw_dump_fallback(
        messages,
        reason="timeout",
        agent_id="main",
        session_key="agent:main:webchat:s1",
    )

    assert len(calls) == 2
    assert first.mode == "error"
    assert first.flushed_paths == []
    assert first.raw_reason is None
    assert first.error == "raw fallback memory_save failed: disk full"
    assert first.result_status == "archive_failed"
    assert second.mode == "error"
    assert [row["scope"] for row in receipt_rows] == ["repair", "repair"]
    assert [row["status"] for row in receipt_rows] == ["repair_failed", "repair_failed"]


@pytest.mark.asyncio
async def test_session_flush_archive_failed_without_checkpoint_records_checkpoint_failed() -> None:
    async def handler(call: ToolCall) -> ToolResult:
        return ToolResult(
            tool_use_id=call.tool_use_id,
            tool_name=call.tool_name,
            content="disk full",
            is_error=True,
        )

    receipt_rows: list[dict[str, Any]] = []

    async def receipt_writer(_receipt: FlushReceipt, **row: Any) -> None:
        receipt_rows.append(row)

    service = SessionFlushService(
        provider_selector=lambda _agent_id: None,
        tool_registry=SimpleNamespace(to_tool_definitions=lambda: []),
        tool_handler=handler,
        receipt_writer=receipt_writer,
    )

    receipt = await service.execute(
        [Message(role="user", content="same transcript")],
        "agent:main:webchat:s1",
        agent_id="main",
        checkpoint_exists=False,
    )

    assert receipt.result_status == "archive_failed"
    assert len(receipt_rows) == 1
    assert receipt_rows[0]["scope"] == "checkpoint"
    assert receipt_rows[0]["status"] == "checkpoint_failed"
    assert receipt_rows[0]["reason"] == "archive_failed"
    assert receipt_rows[0]["target_path"] is None
    assert receipt_rows[0]["content_hash"] == receipt.content_hash


@pytest.mark.asyncio
async def test_session_flush_execute_logs_done_receipt_for_raw_fallback(caplog) -> None:
    async def handler(call: ToolCall) -> ToolResult:
        return ToolResult(
            tool_use_id=call.tool_use_id,
            tool_name=call.tool_name,
            content="Saved to memory/.raw_fallbacks/raw.md (0 chunks indexed).",
        )

    service = SessionFlushService(
        provider_selector=lambda _agent_id: None,
        tool_registry=SimpleNamespace(to_tool_definitions=lambda: []),
        tool_handler=handler,
    )
    caplog.set_level(logging.INFO, logger="opensquilla.memory.session_flush")

    receipt = await service.execute(
        [Message(role="user", content="flush this transcript")],
        "agent:main:webchat:s1",
        agent_id="main",
    )

    assert receipt.mode == "raw"
    assert receipt.result_status == "ok_archive_only"
    records = [
        record
        for record in caplog.records
        if record.name == "opensquilla.memory.session_flush"
        and record.getMessage() == "session_flush.done"
    ]
    assert len(records) == 1
    assert records[0].session_key == "agent:main:webchat:s1"
    assert records[0].agent_id == "main"
    assert records[0].flush_mode == "raw"
    assert records[0].raw_reason == "no_provider"
    assert records[0].flushed_paths == receipt.flushed_paths
    assert records[0].flushed_paths[0].startswith("memory/.raw_fallbacks/")
