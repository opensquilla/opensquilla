from __future__ import annotations

import json
from pathlib import Path

import pytest

from opensquilla.engine.tool_result_store import (
    TOOL_RESULT_COMPRESSED_CONTENT_NAME,
    ToolResultStore,
)
from opensquilla.engine.types import ToolCall
from opensquilla.tools import get_default_registry
from opensquilla.tools.builtin import tool_results
from opensquilla.tools.dispatch import build_tool_handler
from opensquilla.tools.types import CallerKind, SafeToolError, ToolContext, current_tool_context


def _write_record(root: Path, *, session_id: str = "session-a") -> str:
    content = "\n".join(
        [
            "alpha",
            "beta context",
            "ERROR target line",
            "delta context",
            "epsilon",
        ]
    )
    record = ToolResultStore(root).write(
        content,
        tool_use_id="call-1",
        tool_name="exec_command",
        session_id=session_id,
        session_key="agent:main:test",
        agent_id="main",
    )
    return record.handle


def _ctx(
    root: Path,
    *,
    session_id: str = "session-a",
    allowed: bool = False,
) -> ToolContext:
    return ToolContext(
        is_owner=True,
        caller_kind=CallerKind.AGENT,
        session_key="agent:main:test",
        agent_id="main",
        tool_result_store_dir=str(root),
        tool_result_store_session_id=session_id,
        allowed_tools={"retrieve_tool_result"} if allowed else None,
    )


def test_tool_result_store_compresses_large_snapshot_over_raw_limit(tmp_path: Path) -> None:
    content = "\n".join("ERROR repeated diagnostic line" for _ in range(20_000))

    record = ToolResultStore(tmp_path).write(
        content,
        tool_use_id="call-large",
        tool_name="grep_search",
        session_id="session-a",
        session_key="agent:main:test",
        agent_id="main",
        max_bytes=8_000,
    )

    assert record.size_bytes > 8_000
    assert record.stored_size_bytes is not None
    assert record.stored_size_bytes <= 8_000
    assert record.storage_encoding == "gzip+utf-8"
    assert list(tmp_path.rglob(TOOL_RESULT_COMPRESSED_CONTENT_NAME))

    reread = ToolResultStore(tmp_path).read(record.handle, session_id="session-a")
    assert reread.content == content
    assert reread.sha256 == record.sha256
    assert reread.stored_size_bytes == record.stored_size_bytes


@pytest.mark.asyncio
async def test_retrieve_tool_result_metadata_reads_current_session_record(tmp_path: Path) -> None:
    handle = _write_record(tmp_path)
    token = current_tool_context.set(_ctx(tmp_path))
    try:
        result = await tool_results.retrieve_tool_result(handle, mode="metadata")
    finally:
        current_tool_context.reset(token)

    assert result.startswith("[tool_result_retrieval]")
    metadata = json.loads(result.split("---\n", 1)[1])
    assert metadata["handle"] == handle
    assert metadata["tool_name"] == "exec_command"
    assert metadata["line_count"] == 5
    assert metadata["storage_encoding"] == "utf-8"


@pytest.mark.asyncio
async def test_retrieve_tool_result_slice_returns_bounded_numbered_lines(tmp_path: Path) -> None:
    handle = _write_record(tmp_path)
    token = current_tool_context.set(_ctx(tmp_path))
    try:
        result = await tool_results.retrieve_tool_result(
            handle,
            mode="slice",
            start_line=2,
            end_line=4,
        )
    finally:
        current_tool_context.reset(token)

    assert "mode: slice" in result
    assert "2| beta context" in result
    assert "3| ERROR target line" in result
    assert "4| delta context" in result
    assert "1| alpha" not in result


@pytest.mark.asyncio
async def test_retrieve_tool_result_grep_returns_match_context(tmp_path: Path) -> None:
    handle = _write_record(tmp_path)
    token = current_tool_context.set(_ctx(tmp_path))
    try:
        result = await tool_results.retrieve_tool_result(
            handle,
            mode="grep",
            pattern="ERROR",
            context_lines=1,
        )
    finally:
        current_tool_context.reset(token)

    assert "[lines 2-4]" in result
    assert "2| beta context" in result
    assert "3| ERROR target line" in result
    assert "4| delta context" in result
    assert "5| epsilon" not in result


@pytest.mark.asyncio
async def test_retrieve_tool_result_query_supports_line_refs(tmp_path: Path) -> None:
    handle = _write_record(tmp_path)
    token = current_tool_context.set(_ctx(tmp_path))
    try:
        result = await tool_results.retrieve_tool_result(handle, query="L3", context_lines=0)
    finally:
        current_tool_context.reset(token)

    assert "mode: query" in result
    assert "3| ERROR target line" in result
    assert "2| beta context" not in result


@pytest.mark.asyncio
async def test_retrieve_tool_result_query_extracts_embedded_line_refs(
    tmp_path: Path,
) -> None:
    handle = _write_record(tmp_path)
    token = current_tool_context.set(_ctx(tmp_path))
    try:
        result = await tool_results.retrieve_tool_result(
            handle,
            query="show L2 and line 4 from search_hints",
            context_lines=0,
        )
    finally:
        current_tool_context.reset(token)

    assert "mode: query" in result
    assert "[lines 2-2]" in result
    assert "2| beta context" in result
    assert "[lines 4-4]" in result
    assert "4| delta context" in result
    assert "3| ERROR target line" not in result


@pytest.mark.asyncio
async def test_retrieve_tool_result_query_extracts_embedded_line_ranges(
    tmp_path: Path,
) -> None:
    handle = _write_record(tmp_path)
    token = current_tool_context.set(_ctx(tmp_path))
    try:
        result = await tool_results.retrieve_tool_result(
            handle,
            query="diagnostics around L2-L4",
            context_lines=0,
        )
    finally:
        current_tool_context.reset(token)

    assert "[lines 2-4]" in result
    assert "2| beta context" in result
    assert "3| ERROR target line" in result
    assert "4| delta context" in result
    assert "5| epsilon" not in result


@pytest.mark.asyncio
async def test_retrieve_tool_result_query_supports_text_search(tmp_path: Path) -> None:
    handle = _write_record(tmp_path)
    token = current_tool_context.set(_ctx(tmp_path))
    try:
        result = await tool_results.retrieve_tool_result(handle, query="ERROR", context_lines=1)
    finally:
        current_tool_context.reset(token)

    assert "mode: query" in result
    assert "[lines 2-4]" in result
    assert "3| ERROR target line" in result


@pytest.mark.asyncio
async def test_retrieve_tool_result_normalizes_qwen_style_mixed_arguments(
    tmp_path: Path,
) -> None:
    handle = _write_record(tmp_path)
    token = current_tool_context.set(_ctx(tmp_path))
    try:
        grep_result = await tool_results.retrieve_tool_result(
            handle,
            mode="not_a_mode",
            pattern="ERROR",
            limit=1000,
        )
        query_result = await tool_results.retrieve_tool_result(
            handle,
            mode="grep",
            query="ERROR",
            max_chars=1000,
        )
        slice_result = await tool_results.retrieve_tool_result(
            handle,
            start_line=2,
            end_line=3,
        )
    finally:
        current_tool_context.reset(token)

    assert "mode: grep" in grep_result
    assert "3| ERROR target line" in grep_result
    assert "mode: query" in query_result
    assert "3| ERROR target line" in query_result
    assert "mode: slice" in slice_result
    assert "2| beta context" in slice_result
    assert "3| ERROR target line" in slice_result


@pytest.mark.asyncio
async def test_retrieve_tool_result_accepts_handle_from_projection_line(
    tmp_path: Path,
) -> None:
    handle = _write_record(tmp_path)
    token = current_tool_context.set(_ctx(tmp_path))
    try:
        result = await tool_results.retrieve_tool_result(
            f"tool_result_handle: {handle}",
            mode="metadata",
        )
    finally:
        current_tool_context.reset(token)

    assert "mode: metadata" in result
    assert f'"handle": "{handle}"' in result


@pytest.mark.asyncio
async def test_retrieve_tool_result_raw_slice_returns_continuation(
    tmp_path: Path,
) -> None:
    handle = _write_record(tmp_path)
    token = current_tool_context.set(_ctx(tmp_path))
    try:
        result = await tool_results.retrieve_tool_result(
            handle,
            mode="raw_slice",
            offset=0,
            limit=12,
        )
    finally:
        current_tool_context.reset(token)

    assert "mode: raw_slice" in result
    assert "offset: 0" in result
    assert "returned_chars: 12" in result
    assert "continuation.next_call_strategy: raw_slice_offset" in result
    assert '"offset": 12' in result
    assert '"mode": "raw_slice"' in result


@pytest.mark.asyncio
async def test_retrieve_tool_result_query_clip_includes_larger_retry_continuation(
    tmp_path: Path,
) -> None:
    content = "\n".join(f"ERROR repeated diagnostic line {index}" for index in range(80))
    record = ToolResultStore(tmp_path).write(
        content,
        tool_use_id="call-large-query",
        tool_name="exec_command",
        session_id="session-a",
        session_key="agent:main:test",
        agent_id="main",
    )
    token = current_tool_context.set(_ctx(tmp_path))
    try:
        result = await tool_results.retrieve_tool_result(
            record.handle,
            query="ERROR",
            context_lines=1,
            max_chars=500,
        )
    finally:
        current_tool_context.reset(token)

    assert len(result) <= 500
    assert "truncated" in result
    assert "continuation.next_call_strategy: same_query_larger_max_chars" in result
    assert '"query": "ERROR"' in result
    assert '"max_chars": 2000' in result


@pytest.mark.asyncio
async def test_retrieve_tool_result_clips_large_output(tmp_path: Path) -> None:
    handle = _write_record(tmp_path)
    token = current_tool_context.set(_ctx(tmp_path))
    try:
        result = await tool_results.retrieve_tool_result(
            handle,
            mode="head_tail",
            max_chars=90,
        )
    finally:
        current_tool_context.reset(token)

    assert len(result) <= 90
    assert "truncated" in result


@pytest.mark.asyncio
async def test_retrieve_tool_result_rejects_cross_session_handle(tmp_path: Path) -> None:
    handle = _write_record(tmp_path, session_id="session-a")
    token = current_tool_context.set(_ctx(tmp_path, session_id="session-b"))
    try:
        with pytest.raises(SafeToolError) as exc_info:
            await tool_results.retrieve_tool_result(handle)
    finally:
        current_tool_context.reset(token)

    assert "current session" in exc_info.value.user_message


def test_retrieve_tool_result_is_hidden_by_default_but_explicitly_allowable() -> None:
    registry = get_default_registry()
    assert registry.get("retrieve_tool_result") is not None

    default_names = {
        tool.name
        for tool in registry.to_tool_definitions(
            ToolContext(is_owner=True, caller_kind=CallerKind.AGENT)
        )
    }
    assert "retrieve_tool_result" not in default_names

    allowed_names = {
        tool.name
        for tool in registry.to_tool_definitions(
            ToolContext(
                is_owner=True,
                caller_kind=CallerKind.AGENT,
                allowed_tools={"retrieve_tool_result"},
            )
        )
    }
    assert allowed_names == {"retrieve_tool_result"}


def test_retrieve_tool_result_schema_guides_projected_output_recovery() -> None:
    definitions = get_default_registry().to_tool_definitions(
        ToolContext(
            is_owner=True,
            caller_kind=CallerKind.AGENT,
            allowed_tools={"retrieve_tool_result"},
        )
    )

    definition = definitions[0]
    assert definition.name == "retrieve_tool_result"
    assert "aggregate_tool_result_compacted" in definition.description
    assert "before acting on a projected result" in definition.description
    properties = definition.input_schema.properties
    assert "Prefer query" in properties["mode"]["description"]
    assert "raw_slice" in properties["mode"]["description"]
    assert "failing test name" in properties["query"]["description"]
    assert "offset" in properties
    assert "limit" in properties


@pytest.mark.asyncio
async def test_retrieve_tool_result_dispatch_uses_tool_context(tmp_path: Path) -> None:
    handle = _write_record(tmp_path)
    handler = build_tool_handler(get_default_registry(), _ctx(tmp_path, allowed=True))

    result = await handler(
        ToolCall(
            tool_use_id="call-dispatch",
            tool_name="retrieve_tool_result",
            arguments={"handle": handle, "mode": "grep", "pattern": "target"},
        )
    )

    assert result.is_error is False
    assert "ERROR target line" in result.content
