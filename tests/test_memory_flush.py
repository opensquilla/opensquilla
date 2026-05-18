from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest
import structlog.testing

from opensquilla.engine import Agent, AgentConfig
from opensquilla.memory.flush import resolve_flush_plan
from opensquilla.memory.protocols import MemoryToolHandler
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
async def test_agent_background_flush_service_failure_enters_backoff_without_completion_log(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import opensquilla.engine.agent as agent_module

    async def fake_compact_context(_request):
        return SimpleNamespace(
            removed_count=0,
            summary="",
            kept_entries=[{"role": "user", "content": "hello"}],
        )

    class FailingFlushService:
        async def execute(self, *_args, **_kwargs):
            raise RuntimeError("flush service unavailable")

    monkeypatch.setattr(agent_module, "compact_context", fake_compact_context)
    agent = Agent(
        provider=None,  # type: ignore[arg-type]
        config=AgentConfig(
            context_window_tokens=100,
            context_overflow_threshold=0.5,
            flush_backoff_initial_seconds=10.0,
            flush_backoff_max_seconds=20.0,
        ),
    )
    agent._session_flush_service = FailingFlushService()
    messages = [Message(role="user", content="hello")]

    with structlog.testing.capture_logs() as captured:
        await agent._check_context_overflow(messages, 60)

    events = [record["event"] for record in captured]
    assert "memory_flush.service_failed" in events
    assert "memory_flush.completed_after_compaction" not in events
    assert "memory_flush.background_failed" in events
    assert agent._flush_backoff_until > time.monotonic()
    assert agent._flush_backoff_seconds == 10.0


@pytest.mark.asyncio
async def test_agent_background_flush_done_callback_and_await_path_emit_one_terminal_log(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import opensquilla.engine.agent as agent_module

    async def fake_compact_context(_request):
        return SimpleNamespace(
            removed_count=0,
            summary="",
            kept_entries=[{"role": "user", "content": "hello"}],
        )

    async def failing_flush(_plan, _messages):
        raise RuntimeError("flush exploded")

    monkeypatch.setattr(agent_module, "compact_context", fake_compact_context)
    agent = Agent(
        provider=None,  # type: ignore[arg-type]
        config=AgentConfig(
            context_window_tokens=100,
            context_overflow_threshold=0.5,
            flush_backoff_initial_seconds=10.0,
            flush_backoff_max_seconds=20.0,
        ),
    )
    monkeypatch.setattr(agent, "_run_flush", failing_flush)
    messages = [Message(role="user", content="hello")]

    with structlog.testing.capture_logs() as captured:
        await agent._check_context_overflow(messages, 60)

    terminal_events = [
        record["event"]
        for record in captured
        if record["event"]
        in {
            "memory_flush.await_failed",
            "memory_flush.background_failed",
            "memory_flush.completed_after_compaction",
        }
    ]
    assert terminal_events == ["memory_flush.background_failed"]
    assert agent._active_flush_task is None
    assert agent._flush_backoff_until > time.monotonic()


@pytest.mark.asyncio
async def test_agent_background_flush_success_after_timeout_does_not_clear_retry_backoff_early(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import opensquilla.engine.agent as agent_module

    async def fake_compact_context(_request):
        return SimpleNamespace(
            removed_count=0,
            summary="",
            kept_entries=[{"role": "user", "content": "hello"}],
        )

    finish_flush = asyncio.Event()

    async def delayed_flush(_plan, _messages):
        await finish_flush.wait()

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
    monkeypatch.setattr(agent, "_run_flush", delayed_flush)
    messages = [Message(role="user", content="hello")]

    await agent._check_context_overflow(messages, 60)
    timeout_backoff_until = agent._flush_backoff_until

    finish_flush.set()
    await asyncio.wait_for(agent._active_flush_task, timeout=1)
    await asyncio.sleep(0)

    assert timeout_backoff_until > time.monotonic()
    assert agent._flush_backoff_until == timeout_backoff_until
    assert agent._flush_backoff_seconds == 10.0
