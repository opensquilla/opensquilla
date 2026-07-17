from __future__ import annotations

import asyncio
import json
import sys
from types import SimpleNamespace
from typing import Any

import pytest

from opensquilla.cli.gateway_client import (
    GatewayClient,
    GatewayRPCError,
    _normalize_session_error_payload,
    _task_terminal_as_session_event,
    session_history_all,
)

_STOP = object()


class _FakeWebSocket:
    def __init__(self, recv_frames: list[dict[str, Any]] | None = None) -> None:
        self._recv_frames = list(recv_frames or [])
        self.sent: list[str] = []
        self.iter_queue: asyncio.Queue[str | object] = asyncio.Queue()
        self.closed = False

    async def recv(self) -> str:
        if not self._recv_frames:
            raise AssertionError("unexpected recv() call")
        return json.dumps(self._recv_frames.pop(0))

    async def send(self, payload: str) -> None:
        self.sent.append(payload)

    async def close(self) -> None:
        self.closed = True

    def __aiter__(self) -> _FakeWebSocket:
        return self

    async def __anext__(self) -> str:
        item = await self.iter_queue.get()
        if item is _STOP:
            raise StopAsyncIteration
        assert isinstance(item, str)
        return item


class _BrokenSendWebSocket:
    async def send(self, payload: str) -> None:
        raise RuntimeError("socket already closed")


async def _wait_for(predicate, *, timeout: float = 1.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError("condition was not met before timeout")
        await asyncio.sleep(0.005)


def _install_fake_websockets(monkeypatch: pytest.MonkeyPatch, ws: _FakeWebSocket) -> None:
    async def _connect(url: str) -> _FakeWebSocket:
        return ws

    monkeypatch.setitem(sys.modules, "websockets", SimpleNamespace(connect=_connect))


def test_task_terminal_event_uses_terminal_message() -> None:
    event = _task_terminal_as_session_event(
        "task.timeout",
        {
            "task_id": "task-1",
            "terminal_reason": "timeout",
            "terminal_message": "The task timed out before it could finish.",
            "error_message": "Gateway task timeout: Stream idle for more than 60s",
        },
    )

    assert event is not None
    assert event["event"] == "session.event.error"
    assert event["message"] == "The task timed out before it could finish."
    assert "Gateway task" not in event["message"]


def test_session_error_payload_is_normalized_for_gateway_client() -> None:
    payload = _normalize_session_error_payload(
        {
            "message": "Iteration 1 exceeded iteration_timeout",
            "code": "iteration_timeout",
        }
    )

    assert payload["message"] == "The task timed out before it could finish."
    assert payload["terminal_message"] == "The task timed out before it could finish."
    assert payload["error_message"] == "The task timed out before it could finish."


def test_gateway_client_error_normalization_preserves_generic_error_detail() -> None:
    payload = _normalize_session_error_payload(
        {
            "message": "Tool failed with exit code 2",
            "code": "agent_error",
        }
    )

    assert payload["message"] == "The task failed before it could finish."
    assert payload["error_message"] == "Tool failed with exit code 2"


def _handshake_frames(*, keepalive_ms: int = 60_000) -> list[dict[str, Any]]:
    return [
        {"type": "event", "event": "connect.challenge", "payload": {"nonce": "n"}},
        {
            "type": "hello-ok",
            "policy": {"client_ws_keepalive_timeout_ms": keepalive_ms},
        },
    ]


@pytest.mark.asyncio
async def test_heartbeat_interval_derived_from_hello_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ws = _FakeWebSocket(_handshake_frames(keepalive_ms=60_000))
    _install_fake_websockets(monkeypatch, ws)
    client = GatewayClient()

    await client.connect()
    try:
        assert client._heartbeat_interval == 24.0  # noqa: SLF001
        assert client._heartbeat_task is not None  # noqa: SLF001
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_heartbeat_interval_stays_below_short_hello_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ws = _FakeWebSocket(_handshake_frames(keepalive_ms=2_000))
    _install_fake_websockets(monkeypatch, ws)
    client = GatewayClient()

    await client.connect()
    try:
        assert client._heartbeat_interval == 0.8  # noqa: SLF001
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_heartbeat_loop_sends_text_ping_not_rpc() -> None:
    ws = _FakeWebSocket()
    client = GatewayClient()
    client._ws = ws  # noqa: SLF001
    client._heartbeat_interval = 0.01  # noqa: SLF001

    task = asyncio.create_task(client._heartbeat_loop())  # noqa: SLF001
    try:
        await _wait_for(lambda: bool(ws.sent))
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    frame = json.loads(ws.sent[0])
    assert frame == {"type": "ping"}
    assert "id" not in frame
    assert "method" not in frame


@pytest.mark.asyncio
async def test_listener_ignores_pong_frames() -> None:
    ws = _FakeWebSocket()
    client = GatewayClient()
    client._ws = ws  # noqa: SLF001

    task = asyncio.create_task(client._listen())  # noqa: SLF001
    try:
        await ws.iter_queue.put(json.dumps({"type": "pong"}))
        await asyncio.sleep(0.02)
        assert client._recv_queue.empty()  # noqa: SLF001
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_close_cancels_heartbeat(monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _FakeWebSocket(_handshake_frames(keepalive_ms=60_000))
    _install_fake_websockets(monkeypatch, ws)
    client = GatewayClient()

    await client.connect()
    heartbeat_task = client._heartbeat_task  # noqa: SLF001
    assert heartbeat_task is not None

    await client.close()

    assert heartbeat_task.done()
    assert ws.closed is True


@pytest.mark.asyncio
async def test_listener_close_stops_heartbeat_task() -> None:
    ws = _FakeWebSocket()
    client = GatewayClient()
    client._ws = ws  # noqa: SLF001
    client._heartbeat_interval = 60.0  # noqa: SLF001
    client._heartbeat_task = asyncio.create_task(client._heartbeat_loop(ws))  # noqa: SLF001

    listener_task = asyncio.create_task(client._listen())  # noqa: SLF001
    await ws.iter_queue.put(_STOP)
    await _wait_for(lambda: client._connection_error is not None)  # noqa: SLF001

    assert client._heartbeat_task.done()  # noqa: SLF001
    await listener_task


@pytest.mark.asyncio
async def test_call_after_send_failure_raises_clear_connection_error() -> None:
    client = GatewayClient()
    client._ws = _BrokenSendWebSocket()  # noqa: SLF001

    with pytest.raises(ConnectionError, match="Gateway connection lost"):
        await client._call("sessions.messages.subscribe", {"key": "agent:main:x"})  # noqa: SLF001

    assert client._pending == {}  # noqa: SLF001


@pytest.mark.asyncio
async def test_session_history_forwards_optional_paging_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = GatewayClient()
    calls: list[tuple[str, dict[str, Any]]] = []

    async def fake_call(method: str, params: dict[str, Any]) -> dict[str, Any]:
        calls.append((method, params))
        return {"messages": []}

    monkeypatch.setattr(client, "_call", fake_call)

    await client.session_history(
        "agent:main:test",
        limit=25,
        before="12|message-12",
        include_canonical=True,
        include_summaries=False,
    )

    assert calls == [
        (
            "chat.history",
            {
                "sessionKey": "agent:main:test",
                "limit": 25,
                "before": "12|message-12",
                "includeCanonical": True,
                "includeSummaries": False,
            },
        )
    ]

    calls.clear()
    await client.session_history("agent:main:test", limit=5)
    assert calls == [
        ("chat.history", {"sessionKey": "agent:main:test", "limit": 5})
    ]


@pytest.mark.asyncio
async def test_session_history_all_orders_and_deduplicates_pages() -> None:
    calls: list[dict[str, Any]] = []

    async def fetch(
        session_key: str,
        limit: int = 1000,
        *,
        before: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        calls.append(
            {"session_key": session_key, "limit": limit, "before": before, **kwargs}
        )
        if before is None:
            return {
                "messages": [
                    {"message_id": "m3", "role": "user", "text": "three"},
                    {"message_id": "m4", "role": "assistant", "text": "four"},
                ],
                "has_more": True,
                "oldest_cursor": "3|3",
                "newest_cursor": "4|4",
            }
        return {
            "messages": [
                {"message_id": "m1", "role": "user", "text": "one"},
                {"message_id": "m2", "role": "assistant", "text": "two"},
                {"message_id": "m2", "role": "assistant", "text": "two"},
            ],
            "has_more": False,
            "oldest_cursor": "1|1",
            "newest_cursor": "2|2",
        }

    result = await session_history_all(fetch, "agent:main:test", page_size=2)

    assert [message["message_id"] for message in result["messages"]] == [
        "m1",
        "m2",
        "m3",
        "m4",
    ]
    assert result["has_more"] is False
    assert result["loaded_count"] == 4
    assert result["oldest_cursor"] == "1|1"
    assert result["newest_cursor"] == "4|4"
    assert calls == [
        {
            "session_key": "agent:main:test",
            "limit": 2,
            "before": None,
            "include_canonical": True,
            "include_summaries": False,
        },
        {
            "session_key": "agent:main:test",
            "limit": 2,
            "before": "3|3",
            "include_canonical": True,
            "include_summaries": False,
        },
    ]


@pytest.mark.asyncio
async def test_session_history_all_rejects_non_advancing_cursor() -> None:
    async def fetch(
        session_key: str,
        limit: int = 1000,
        *,
        before: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return {
            "messages": [{"message_id": "m3", "role": "user", "text": "three"}],
            "has_more": True,
            "oldest_cursor": "3|3",
            "newest_cursor": "3|3",
        }

    with pytest.raises(GatewayRPCError, match="cursor did not advance"):
        await session_history_all(fetch, "agent:main:test")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "replacement_page",
    [
        {
            "messages": [],
            "has_more": False,
            "oldest_cursor": None,
            "newest_cursor": None,
        },
        {
            "messages": [
                {"message_id": "replacement", "role": "user", "text": "new session"}
            ],
            "has_more": False,
            "oldest_cursor": "10|10",
            "newest_cursor": "10|10",
        },
    ],
)
async def test_session_history_all_rejects_reset_or_unknown_cursor_page(
    replacement_page: dict[str, Any],
) -> None:
    async def fetch(
        session_key: str,
        limit: int = 1000,
        *,
        before: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if before is not None:
            return replacement_page
        return {
            "messages": [
                {"message_id": "m3", "role": "user", "text": "three"},
                {"message_id": "m4", "role": "assistant", "text": "four"},
            ],
            "has_more": True,
            "oldest_cursor": "3|3",
            "newest_cursor": "4|4",
        }

    with pytest.raises(GatewayRPCError) as exc_info:
        await session_history_all(fetch, "agent:main:test")

    assert exc_info.value.code == "HISTORY_CURSOR_INVALIDATED"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "code"),
    [
        ("canonical_available", "CANONICAL_HISTORY_UNAVAILABLE"),
        ("canonical_complete", "CANONICAL_HISTORY_INCOMPLETE"),
    ],
)
async def test_session_history_all_refuses_partial_canonical_export(
    field: str,
    code: str,
) -> None:
    async def fetch(
        session_key: str,
        limit: int = 1000,
        *,
        before: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return {
            "messages": [{"message_id": "m1", "role": "user", "text": "one"}],
            "has_more": False,
            field: False,
        }

    with pytest.raises(GatewayRPCError) as exc_info:
        await session_history_all(fetch, "agent:main:test")

    assert exc_info.value.code == code
