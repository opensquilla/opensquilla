"""Tests for /api/usage RPC handlers — focused on cache_read / cache_write totals."""

import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace

from opensquilla.engine.usage import UsageTracker
from opensquilla.gateway import rpc_usage
from opensquilla.gateway.rpc.registry import RpcContext
from opensquilla.session.manager import SessionManager
from opensquilla.session.storage import SessionStorage
from opensquilla.session.usage_rpc import (
    usage_cost_rpc_payload,
    usage_status_rpc_payload,
)


def _ctx(*, session_manager=None, usage_tracker=None) -> RpcContext:
    return RpcContext(
        conn_id="test",
        session_manager=session_manager,
        usage_tracker=usage_tracker,
        config=SimpleNamespace(llm=SimpleNamespace(model="claude-opus-4-7")),
    )


async def _handle_usage_status(_params, ctx: RpcContext):
    return await usage_status_rpc_payload(
        session_manager=ctx.session_manager,
        usage_tracker=ctx.usage_tracker,
        config=ctx.config,
        now_ms=rpc_usage._now_ms(),
    )


async def _handle_usage_cost(_params, ctx: RpcContext):
    return await usage_cost_rpc_payload(
        session_manager=ctx.session_manager,
        usage_tracker=ctx.usage_tracker,
        config=ctx.config,
        now_ms=rpc_usage._now_ms(),
    )


def test_usage_status_tracker_only_path_surfaces_cache_totals() -> None:
    """When session_manager is None, cache numbers must come from the in-memory tracker."""
    tracker = UsageTracker()
    tracker.add(
        "agent:webchat:abc",
        input_tokens=1000,
        output_tokens=50,
        model_id="claude-opus-4-7",
        cache_read_tokens=200,
        cache_write_tokens=80,
    )

    ctx = _ctx(session_manager=None, usage_tracker=tracker)
    payload = asyncio.run(_handle_usage_status(None, ctx))

    assert payload["totalCacheReadTokens"] == 200
    assert payload["totalCacheWriteTokens"] == 80
    assert payload["totalSessions"] == 1

    [row] = payload["sessions"]
    # camelCase keys
    assert row["cacheReadTokens"] == 200
    assert row["cacheWriteTokens"] == 80
    # snake_case aliases for the legacy UI
    assert row["cache_read_tokens"] == 200
    assert row["cache_write_tokens"] == 80
    assert row["costSource"] == "opensquilla_estimate"
    assert row["cost_source"] == "opensquilla_estimate"
    assert row["costEphemeral"] is True
    assert row["cost_ephemeral"] is True
    assert row["billedCostUsd"] == 0.0
    assert row["estimatedCostUsd"] == row["costUsd"]


class _FakeSessionManager:
    def __init__(self, sessions):
        self._sessions = sessions

    async def list_sessions(self):
        return self._sessions


def test_usage_status_session_manager_path_reads_cache_fields() -> None:
    """When session_manager has records, getattr on cache_read/cache_write must flow through."""
    session = SimpleNamespace(
        session_key="agent:webchat:xyz",
        status="running",
        input_tokens=5000,
        output_tokens=200,
        estimated_cost_usd=0.04,
        cache_read=300,
        cache_write=120,
        model="claude-opus-4-7",
    )
    sm = _FakeSessionManager([session])

    ctx = _ctx(session_manager=sm, usage_tracker=UsageTracker())
    payload = asyncio.run(_handle_usage_status(None, ctx))

    assert payload["totalCacheReadTokens"] == 300
    assert payload["totalCacheWriteTokens"] == 120
    [row] = payload["sessions"]
    assert row["cacheReadTokens"] == 300
    assert row["cacheWriteTokens"] == 120
    assert row["costUsd"] == 0.04
    assert row["estimatedCostUsd"] == 0.04
    assert row["billedCostUsd"] == 0.0
    assert row["costSource"] == "opensquilla_estimate"
    assert row["costEphemeral"] is False


def test_usage_status_exposes_session_timestamp_aliases() -> None:
    session = SimpleNamespace(
        session_key="agent:webchat:timed",
        status="finished",
        input_tokens=500,
        output_tokens=20,
        estimated_cost_usd=0.01,
        cache_read=12,
        cache_write=3,
        model="claude-opus-4-7",
        created_at=1000,
        updated_at=2000,
        started_at=3000,
        ended_at=4000,
    )
    sm = _FakeSessionManager([session])

    ctx = _ctx(session_manager=sm, usage_tracker=UsageTracker())
    payload = asyncio.run(_handle_usage_status(None, ctx))

    [row] = payload["sessions"]
    assert row["createdAt"] == 1000
    assert row["created_at"] == 1000
    assert row["updatedAt"] == 2000
    assert row["updated_at"] == 2000
    assert row["startedAt"] == 3000
    assert row["started_at"] == 3000
    assert row["endedAt"] == 4000
    assert row["ended_at"] == 4000


def test_usage_status_tracker_only_rows_have_current_timestamp_aliases(monkeypatch) -> None:
    tracker = UsageTracker()
    tracker.add(
        "agent:webchat:live",
        input_tokens=100,
        output_tokens=10,
        model_id="claude-opus-4-7",
    )

    monkeypatch.setattr(rpc_usage, "_now_ms", lambda: 123456)
    ctx = _ctx(session_manager=None, usage_tracker=tracker)
    payload = asyncio.run(_handle_usage_status(None, ctx))

    [row] = payload["sessions"]
    assert row["createdAt"] == 123456
    assert row["created_at"] == row["createdAt"]
    assert row["updatedAt"] == 123456
    assert row["updated_at"] == row["updatedAt"]
    assert row["startedAt"] is None
    assert row["started_at"] is None
    assert row["endedAt"] is None
    assert row["ended_at"] is None


def test_usage_status_exposes_persisted_cost_components_and_source() -> None:
    session = SimpleNamespace(
        session_key="agent:webchat:mixed",
        status="running",
        input_tokens=5000,
        output_tokens=200,
        total_cost_usd=0.07,
        billed_cost_usd=0.06,
        estimated_cost_component_usd=0.01,
        cost_source="mixed",
        missing_cost_entries=0,
        cache_read=300,
        cache_write=120,
        model="claude-opus-4-7",
    )
    sm = _FakeSessionManager([session])

    ctx = _ctx(session_manager=sm, usage_tracker=UsageTracker())
    payload = asyncio.run(_handle_usage_status(None, ctx))

    [row] = payload["sessions"]
    assert row["costUsd"] == 0.07
    assert row["billedCostUsd"] == 0.06
    assert row["estimatedCostUsd"] == 0.01
    assert row["costSource"] == "mixed"
    assert row["missingCostEntries"] == 0
    assert row["cost_ephemeral"] is False


def test_usage_status_merges_tracker_and_session_manager_cache_totals() -> None:
    """Tracker-only sessions (no session_manager record) must still contribute cache totals."""
    db_session = SimpleNamespace(
        session_key="agent:webchat:db",
        status="running",
        input_tokens=1000,
        output_tokens=50,
        estimated_cost_usd=0.01,
        cache_read=400,
        cache_write=200,
        model="claude-opus-4-7",
    )
    sm = _FakeSessionManager([db_session])

    tracker = UsageTracker()
    tracker.add(
        "tracker-only-session",
        input_tokens=500,
        output_tokens=20,
        model_id="claude-opus-4-7",
        cache_read_tokens=50,
        cache_write_tokens=10,
    )

    ctx = _ctx(session_manager=sm, usage_tracker=tracker)
    payload = asyncio.run(_handle_usage_status(None, ctx))

    # cache_read = 400 (db) + 50 (tracker) = 450
    # cache_write = 200 (db) + 10 (tracker) = 210
    assert payload["totalCacheReadTokens"] == 450
    assert payload["totalCacheWriteTokens"] == 210
    assert payload["totalSessions"] == 2
    rows = {row["session"]: row for row in payload["sessions"]}
    assert rows["agent:webchat:db"]["costSource"] == "opensquilla_estimate"
    assert rows["tracker-only-session"]["costSource"] == "opensquilla_estimate"
    assert rows["tracker-only-session"]["costEphemeral"] is True


def test_usage_status_prefers_persisted_row_over_same_session_tracker_row() -> None:
    db_session = SimpleNamespace(
        session_key="agent:webchat:same",
        status="running",
        input_tokens=1000,
        output_tokens=50,
        total_cost_usd=0.004,
        billed_cost_usd=0.004,
        estimated_cost_component_usd=0.0,
        cost_source="provider_billed",
        missing_cost_entries=0,
        cache_read=0,
        cache_write=0,
        model="claude-opus-4-7",
    )
    sm = _FakeSessionManager([db_session])
    tracker = UsageTracker()
    tracker.add(
        "agent:webchat:same",
        input_tokens=9000,
        output_tokens=9000,
        model_id="claude-opus-4-7",
    )

    ctx = _ctx(session_manager=sm, usage_tracker=tracker)
    payload = asyncio.run(_handle_usage_status(None, ctx))

    [row] = payload["sessions"]
    assert row["session"] == "agent:webchat:same"
    assert row["costUsd"] == 0.004
    assert row["billedCostUsd"] == 0.004
    assert row["costSource"] == "provider_billed"
    assert row["costEphemeral"] is False


def test_usage_status_reads_real_session_manager_dict_rows_and_deduplicates_tracker() -> None:
    async def scenario():
        storage = SessionStorage(":memory:")
        await storage.connect()
        manager = SessionManager(storage)
        try:
            await manager.create("agent:webchat:real")
            await manager.update(
                "agent:webchat:real",
                input_tokens=1000,
                output_tokens=50,
                total_cost_usd=0.004,
                billed_cost_usd=0.004,
                estimated_cost_component_usd=0.0,
                cost_source="provider_billed",
                missing_cost_entries=0,
                cache_read=12,
                cache_write=3,
                model="claude-opus-4-7",
            )
            tracker = UsageTracker()
            tracker.add(
                "agent:webchat:real",
                input_tokens=9000,
                output_tokens=9000,
                model_id="claude-opus-4-7",
            )
            ctx = _ctx(session_manager=manager, usage_tracker=tracker)
            return await _handle_usage_status(None, ctx)
        finally:
            await storage.close()

    payload = asyncio.run(scenario())

    [row] = payload["sessions"]
    assert payload["totalSessions"] == 1
    assert row["session"] == "agent:webchat:real"
    assert row["inputTokens"] == 1000
    assert row["outputTokens"] == 50
    assert row["cacheReadTokens"] == 12
    assert row["cacheWriteTokens"] == 3
    assert row["costUsd"] == 0.004
    assert row["billedCostUsd"] == 0.004
    assert row["costSource"] == "provider_billed"
    assert row["costEphemeral"] is False


def test_usage_cost_breakdown_carries_cache_fields() -> None:
    """The `usage.cost` RPC must surface cache numbers per-row in the breakdown."""
    session = SimpleNamespace(
        session_key="agent:webchat:xyz",
        input_tokens=5000,
        output_tokens=200,
        estimated_cost_usd=0.04,
        cache_read=300,
        cache_write=120,
        model="claude-opus-4-7",
    )
    sm = _FakeSessionManager([session])
    ctx = _ctx(session_manager=sm, usage_tracker=UsageTracker())

    payload = asyncio.run(_handle_usage_cost(None, ctx))
    [row] = payload["breakdown"]
    assert row["cacheReadTokens"] == 300
    assert row["cacheWriteTokens"] == 120
    assert row["costUsd"] == 0.04
    assert row["estimatedCostUsd"] == 0.04
    assert row["costSource"] == "opensquilla_estimate"


def test_usage_cost_exposes_session_timestamp_aliases() -> None:
    session = SimpleNamespace(
        session_key="agent:webchat:timed-cost",
        input_tokens=500,
        output_tokens=20,
        estimated_cost_usd=0.01,
        cache_read=12,
        cache_write=3,
        model="claude-opus-4-7",
        created_at=1100,
        updated_at=2200,
        started_at=3300,
        ended_at=4400,
    )
    sm = _FakeSessionManager([session])
    ctx = _ctx(session_manager=sm, usage_tracker=UsageTracker())

    payload = asyncio.run(_handle_usage_cost(None, ctx))

    [row] = payload["breakdown"]
    assert row["createdAt"] == 1100
    assert row["created_at"] == 1100
    assert row["updatedAt"] == 2200
    assert row["updated_at"] == 2200
    assert row["startedAt"] == 3300
    assert row["started_at"] == 3300
    assert row["endedAt"] == 4400
    assert row["ended_at"] == 4400


def test_usage_status_no_data_returns_zeros() -> None:
    """Empty environment: all totals are 0, no error."""
    ctx = _ctx(session_manager=None, usage_tracker=UsageTracker())
    payload = asyncio.run(_handle_usage_status(None, ctx))

    assert payload["totalCacheReadTokens"] == 0
    assert payload["totalCacheWriteTokens"] == 0
    assert payload["totalSessions"] == 0


def test_gateway_rpc_usage_status_handler_delegates_to_session_payload(monkeypatch) -> None:
    seen = {}

    async def fake_payload(**kwargs):
        seen.update(kwargs)
        return {"ok": True}

    tracker = UsageTracker()
    session_manager = object()
    ctx = _ctx(session_manager=session_manager, usage_tracker=tracker)
    monkeypatch.setattr(rpc_usage, "_now_ms", lambda: 123)
    monkeypatch.setattr(rpc_usage, "usage_status_rpc_payload", fake_payload)

    payload = asyncio.run(rpc_usage._handle_usage_status(None, ctx))

    assert payload == {"ok": True}
    assert seen == {
        "session_manager": session_manager,
        "usage_tracker": tracker,
        "config": ctx.config,
        "now_ms": 123,
    }


def test_gateway_rpc_usage_delegates_payloads_to_session_boundary() -> None:
    source = Path(rpc_usage.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    top_level_functions = {
        node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    assert "_usage_row" not in top_level_functions
    assert "_tracker_rows" not in top_level_functions
    assert "_resolved_session_cost_fields" not in top_level_functions
    assert "rollup_cost_source" not in source
    assert "opensquilla.observability.usage_rpc" not in source
    assert "opensquilla.session.usage_rpc" in source
    assert "usage_status_rpc_payload" in source
    assert "usage_cost_rpc_payload" in source
