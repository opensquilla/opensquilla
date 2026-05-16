from __future__ import annotations

from types import SimpleNamespace

import pytest

from opensquilla.engine.usage import UsageTracker
from opensquilla.session.usage_rpc import (
    usage_cost_rpc_payload,
    usage_status_rpc_payload,
)


class _FakeSessionManager:
    def __init__(self, sessions):
        self._sessions = sessions

    async def list_sessions(self):
        return self._sessions


def _config(model: str = "gpt-test"):
    return SimpleNamespace(llm=SimpleNamespace(model=model))


@pytest.mark.asyncio
async def test_usage_status_rpc_payload_owns_session_and_tracker_wire_shape() -> None:
    session = SimpleNamespace(
        session_key="agent:webchat:db",
        status="running",
        input_tokens=1000,
        output_tokens=50,
        total_cost_usd=0.004,
        billed_cost_usd=0.004,
        estimated_cost_component_usd=0.0,
        cost_source="provider_billed",
        missing_cost_entries=0,
        cache_read=12,
        cache_write=3,
        model="gpt-db",
    )
    tracker = UsageTracker()
    tracker.add(
        "tracker-only-session",
        input_tokens=500,
        output_tokens=20,
        model_id="gpt-live",
        cache_read_tokens=7,
        cache_write_tokens=2,
    )

    payload = await usage_status_rpc_payload(
        session_manager=_FakeSessionManager([session]),
        usage_tracker=tracker,
        config=_config(),
        now_ms=123456,
    )

    assert payload["totalSessions"] == 2
    assert payload["activeSessions"] == 2
    assert payload["totalInputTokens"] == 1500
    assert payload["totalOutputTokens"] == 70
    assert payload["totalCacheReadTokens"] == 19
    assert payload["totalCacheWriteTokens"] == 5
    rows = {row["session"]: row for row in payload["sessions"]}
    assert rows["agent:webchat:db"]["costSource"] == "provider_billed"
    assert rows["agent:webchat:db"]["costEphemeral"] is False
    assert rows["tracker-only-session"]["costSource"] == "opensquilla_estimate"
    assert rows["tracker-only-session"]["costEphemeral"] is True
    assert rows["tracker-only-session"]["createdAt"] == 123456


@pytest.mark.asyncio
async def test_usage_cost_rpc_payload_owns_breakdown_wire_shape() -> None:
    session = SimpleNamespace(
        session_key="agent:webchat:cost",
        input_tokens=250,
        output_tokens=25,
        estimated_cost_usd=0.01,
        cache_read=4,
        cache_write=1,
        model="gpt-cost",
    )

    payload = await usage_cost_rpc_payload(
        session_manager=_FakeSessionManager([session]),
        usage_tracker=UsageTracker(),
        config=_config(),
        now_ms=1,
    )

    assert payload["totalCostUsd"] == 0.01
    assert payload["breakdown"] == [
        {
            "sessionKey": "agent:webchat:cost",
            "inputTokens": 250,
            "outputTokens": 25,
            "costUsd": 0.01,
            "billedCostUsd": 0.0,
            "estimatedCostUsd": 0.01,
            "costSource": "opensquilla_estimate",
            "missingCostEntries": 0,
            "costEphemeral": False,
            "cacheReadTokens": 4,
            "cacheWriteTokens": 1,
            "createdAt": None,
            "updatedAt": None,
            "startedAt": None,
            "endedAt": None,
            "model": "gpt-cost",
            "session": "agent:webchat:cost",
            "key": "agent:webchat:cost",
            "input_tokens": 250,
            "output_tokens": 25,
            "cost_usd": 0.01,
            "billed_cost_usd": 0.0,
            "estimated_cost_usd": 0.01,
            "cost_source": "opensquilla_estimate",
            "missing_cost_entries": 0,
            "cost_ephemeral": False,
            "cache_read_tokens": 4,
            "cache_write_tokens": 1,
            "created_at": None,
            "updated_at": None,
            "started_at": None,
            "ended_at": None,
        }
    ]
