from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from opensquilla.engine.types import DoneEvent
from opensquilla.observability import install_telemetry, usage_telemetry
from opensquilla.session.storage import SessionStorage


def _config(tmp_path, *, disabled: bool = False):
    return SimpleNamespace(
        state_dir=str(tmp_path / "state"),
        privacy=SimpleNamespace(
            disable_network_observability=disabled,
        ),
    )


def _done(**values: Any) -> DoneEvent:
    defaults = {
        "input_tokens": 100,
        "output_tokens": 20,
        "cached_tokens": 30,
        "cache_write_tokens": 4,
    }
    defaults.update(values)
    return DoneEvent(**defaults)


async def test_records_only_completed_interactive_turns(tmp_path, monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    storage = await SessionStorage.open(str(tmp_path / "sessions.db"))
    config = _config(tmp_path)
    now = datetime(2026, 7, 19, 12, tzinfo=UTC)
    try:
        assert await usage_telemetry.record_completed_turn(
            storage, config=config, run_kind="default", done_event=_done(), now=now
        )
        assert await usage_telemetry.record_completed_turn(
            storage,
            config=config,
            run_kind="channel_turn",
            done_event=_done(input_tokens=7, output_tokens=3),
            now=now,
        )
        assert await usage_telemetry.record_completed_turn(
            storage,
            config=config,
            run_kind="session_turn",
            done_event=_done(
                input_tokens=5,
                output_tokens=2,
                cached_tokens=0,
                cache_write_tokens=0,
            ),
            now=now,
        )
        assert await usage_telemetry.record_completed_turn(
            storage,
            config=config,
            run_kind="web_turn",
            done_event=_done(
                input_tokens=4,
                output_tokens=1,
                cached_tokens=0,
                cache_write_tokens=0,
            ),
            now=now,
        )
        assert not await usage_telemetry.record_completed_turn(
            storage, config=config, run_kind="heartbeat", done_event=_done(), now=now
        )
        assert not await usage_telemetry.record_completed_turn(
            storage, config=config, run_kind="subagent", done_event=_done(), now=now
        )
        assert not await usage_telemetry.record_completed_turn(
            storage, config=config, run_kind="default", done_event=None, now=now
        )

        rows = await storage.list_pending_daily_usage(before_day="2026-07-20")
        assert rows == [
            {
                "day": "2026-07-19",
                "conversation_turns": 4,
                "input_tokens": 116,
                "output_tokens": 26,
                "cached_tokens": 60,
                "cache_write_tokens": 8,
                "updated_at": int(now.timestamp() * 1000),
                "uploaded_at": None,
            }
        ]
    finally:
        await storage.close()


async def test_opt_out_does_not_create_daily_row(tmp_path, monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    storage = await SessionStorage.open(str(tmp_path / "sessions.db"))
    try:
        recorded = await usage_telemetry.record_completed_turn(
            storage,
            config=_config(tmp_path, disabled=True),
            run_kind="default",
            done_event=_done(),
        )
        assert recorded is False
        assert await storage.list_pending_daily_usage(before_day="9999-12-31") == []
    finally:
        await storage.close()


async def test_uploads_pending_aggregates_through_today_and_marks_success(tmp_path, monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    endpoint = "https://example.test/v1/usage"
    monkeypatch.setenv(usage_telemetry.USAGE_TELEMETRY_ENDPOINT_ENV, endpoint)
    config = _config(tmp_path)
    storage = await SessionStorage.open(str(tmp_path / "sessions.db"))
    await storage.record_daily_usage(
        day="2026-07-19",
        input_tokens=10,
        output_tokens=2,
        cached_tokens=3,
        cache_write_tokens=1,
        updated_at=1,
    )
    await storage.record_daily_usage(
        day="2026-07-20",
        input_tokens=99,
        output_tokens=99,
        cached_tokens=99,
        cache_write_tokens=99,
        updated_at=2,
    )
    payloads: list[dict[str, Any]] = []

    async def fake_post(endpoint: str, payload: dict[str, Any]):
        assert endpoint == "https://example.test/v1/usage"
        payloads.append(payload)
        return True, None

    monkeypatch.setattr(usage_telemetry, "_post_payload", fake_post)
    try:
        uploaded = await usage_telemetry.upload_pending_daily_usage(
            storage, config=config, today=date(2026, 7, 20)
        )
        assert uploaded == 2
        assert [payload["day"] for payload in payloads] == ["2026-07-19", "2026-07-20"]
        payload = payloads[0]
        assert payload["event"] == "daily_usage"
        assert payload["sent_at"].endswith("Z")
        assert payload["opensquilla_version"]
        assert payload["install_id"]
        assert len(payload["event_id"]) == 43
        assert payload["conversation_turns"] == 1
        assert payload["input_tokens"] == 10
        assert payload["output_tokens"] == 2
        assert payload["cached_tokens"] == 3
        assert payload["cache_write_tokens"] == 1
        assert "distributor_token" not in payload
        assert "session" not in str(payload).lower()
        assert await storage.list_pending_daily_usage(before_day="2026-07-21") == []
    finally:
        await storage.close()


async def test_new_turn_keeps_snapshot_pending_when_upload_is_in_flight(tmp_path, monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv(
        usage_telemetry.USAGE_TELEMETRY_ENDPOINT_ENV,
        "https://example.test/v1/usage",
    )
    config = _config(tmp_path)
    storage = await SessionStorage.open(str(tmp_path / "sessions.db"))
    await storage.record_daily_usage(
        day="2026-07-20",
        input_tokens=10,
        output_tokens=2,
        cached_tokens=3,
        cache_write_tokens=1,
        updated_at=1,
    )

    async def fake_post(endpoint: str, payload: dict[str, Any]):
        await storage.record_daily_usage(
            day="2026-07-20",
            input_tokens=20,
            output_tokens=4,
            cached_tokens=6,
            cache_write_tokens=2,
            updated_at=2,
        )
        return True, None

    monkeypatch.setattr(usage_telemetry, "_post_payload", fake_post)
    try:
        assert (
            await usage_telemetry.upload_pending_daily_usage(
                storage, config=config, today=date(2026, 7, 20)
            )
            == 1
        )
        rows = await storage.list_pending_daily_usage(before_day="2026-07-21")
        assert len(rows) == 1
        assert rows[0]["conversation_turns"] == 2
        assert rows[0]["input_tokens"] == 30
        assert rows[0]["uploaded_at"] is None
    finally:
        await storage.close()


async def test_hourly_snapshots_reuse_event_id_with_latest_cumulative_totals(tmp_path, monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv(
        usage_telemetry.USAGE_TELEMETRY_ENDPOINT_ENV,
        "https://example.test/v1/usage",
    )
    config = _config(tmp_path)
    storage = await SessionStorage.open(str(tmp_path / "sessions.db"))
    payloads: list[dict[str, Any]] = []

    async def fake_post(endpoint: str, payload: dict[str, Any]):
        payloads.append(payload)
        return True, None

    monkeypatch.setattr(usage_telemetry, "_post_payload", fake_post)
    try:
        await storage.record_daily_usage(
            day="2026-07-20",
            input_tokens=10,
            output_tokens=2,
            cached_tokens=3,
            cache_write_tokens=1,
            updated_at=1,
        )
        assert (
            await usage_telemetry.upload_pending_daily_usage(
                storage, config=config, today=date(2026, 7, 20)
            )
            == 1
        )

        await storage.record_daily_usage(
            day="2026-07-20",
            input_tokens=20,
            output_tokens=4,
            cached_tokens=6,
            cache_write_tokens=2,
            updated_at=2,
        )
        assert (
            await usage_telemetry.upload_pending_daily_usage(
                storage, config=config, today=date(2026, 7, 20)
            )
            == 1
        )

        assert [payload["conversation_turns"] for payload in payloads] == [1, 2]
        assert [payload["input_tokens"] for payload in payloads] == [10, 30]
        assert payloads[0]["event_id"] == payloads[1]["event_id"]
    finally:
        await storage.close()


async def test_upload_loop_attempts_immediately_then_waits_one_hour(monkeypatch):
    attempts: list[tuple[Any, Any]] = []
    delays: list[float] = []
    storage = object()
    config = object()

    async def fake_upload(passed_storage: Any, *, config: Any, today=None) -> int:
        attempts.append((passed_storage, config))
        return 0

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)
        raise asyncio.CancelledError

    monkeypatch.setattr(usage_telemetry, "upload_pending_daily_usage", fake_upload)
    monkeypatch.setattr(usage_telemetry.asyncio, "sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await usage_telemetry.run_daily_usage_upload_loop(storage, config=config)

    assert attempts == [(storage, config)]
    assert delays == [3600]


def test_usage_endpoint_is_independent_from_install_endpoint(monkeypatch):
    monkeypatch.setenv(
        install_telemetry.TELEMETRY_ENDPOINT_ENV,
        "https://install.example.test/v1/install",
    )
    monkeypatch.delenv(usage_telemetry.USAGE_TELEMETRY_ENDPOINT_ENV, raising=False)

    assert usage_telemetry._endpoint() == "https://telemetry.opensquilla.ai/v1/usage"

    monkeypatch.setenv(
        usage_telemetry.USAGE_TELEMETRY_ENDPOINT_ENV,
        "https://usage.example.test/v1/usage",
    )
    assert usage_telemetry._endpoint() == "https://usage.example.test/v1/usage"


async def test_post_uses_event_id_as_idempotency_key(monkeypatch):
    import httpx

    calls: list[dict[str, Any]] = []

    class FakeResponse:
        status_code = 200

    class FakeClient:
        def __init__(self, *, timeout: float) -> None:
            assert timeout == install_telemetry.DEFAULT_TIMEOUT_SECONDS

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def post(self, endpoint: str, *, json: dict[str, Any], headers: dict[str, str]):
            calls.append({"endpoint": endpoint, "json": json, "headers": headers})
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    payload = {"event_id": "stable-event-id", "event": "daily_usage"}

    assert await usage_telemetry._post_payload(
        "https://telemetry.opensquilla.ai/v1/usage",
        payload,
    ) == (True, None)
    assert calls == [
        {
            "endpoint": "https://telemetry.opensquilla.ai/v1/usage",
            "json": payload,
            "headers": {"Idempotency-Key": "stable-event-id"},
        }
    ]
