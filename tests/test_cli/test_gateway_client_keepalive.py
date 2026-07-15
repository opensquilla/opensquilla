from __future__ import annotations

import asyncio
import json
import sys
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from opensquilla.cli.gateway_client import (
    GatewayClient,
    GatewayRPCError,
    _normalize_session_error_payload,
    _task_terminal_as_session_event,
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
async def test_call_preserves_gateway_error_details_for_safe_fallback_decisions() -> None:
    ws = _FakeWebSocket()
    client = GatewayClient()
    client._ws = ws  # noqa: SLF001

    call_task = asyncio.create_task(
        client._call("sessions.steer", {"key": "agent:main:x"})  # noqa: SLF001
    )
    await _wait_for(lambda: bool(ws.sent))
    request_id = json.loads(ws.sent[0])["id"]
    client._pending[request_id].set_result(  # noqa: SLF001
        {
            "ok": False,
            "error": {
                "code": "STEER_RACE_DIRTY",
                "message": "rollback failed",
                "details": {
                    "fallback_safe": False,
                    "orphan_message_id": "message-orphan",
                },
            },
        }
    )

    with pytest.raises(GatewayRPCError) as raised:
        await call_task
    assert raised.value.code == "STEER_RACE_DIRTY"
    assert raised.value.data == {
        "fallback_safe": False,
        "orphan_message_id": "message-orphan",
    }


@pytest.mark.asyncio
async def test_bootstrap_session_uses_additive_snapshot_rpc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = GatewayClient()
    call = AsyncMock(return_value={"session": {"session_key": "agent:main:x"}})
    monkeypatch.setattr(client, "_call", call)

    result = await client.bootstrap_session("agent:main:x", limit=75)

    assert result["session"]["session_key"] == "agent:main:x"
    call.assert_awaited_once_with(
        "sessions.bootstrap",
        {"key": "agent:main:x", "limit": 75},
    )


@pytest.mark.asyncio
async def test_event_multiplexer_broadcasts_without_cross_session_consumption(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = GatewayClient()
    call = AsyncMock(return_value={"replay_complete": True, "current_stream_seq": 4})
    monkeypatch.setattr(client, "_call", call)
    session_a = await client.subscribe_session_events("agent:main:a", since_stream_seq=3)
    session_b = await client.subscribe_session_events("agent:main:b")
    approvals = client.subscribe_global_events(
        {"exec.approval.requested", "exec.approval.resolved"}
    )

    client._publish_event(  # noqa: SLF001
        {
            "type": "event",
            "event": "session.event.text_delta",
            "payload": {
                "session_key": "agent:main:a",
                "stream_seq": 4,
                "text": "hello",
            },
        }
    )
    client._publish_event(  # noqa: SLF001
        {
            "type": "event",
            "event": "exec.approval.requested",
            "payload": {"approval_id": "approval-1", "session_key": "agent:main:a"},
        }
    )

    assert (await session_a.get())["payload"]["text"] == "hello"
    assert (await approvals.get())["payload"]["approval_id"] == "approval-1"
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(session_b.get(), timeout=0.01)
    assert session_a.replay["current_stream_seq"] == 4
    call.assert_any_await(
        "sessions.messages.subscribe",
        {"key": "agent:main:a", "since_stream_seq": 3},
    )

    await session_a.close()
    await session_b.close()
    await approvals.close()


@pytest.mark.asyncio
async def test_send_message_filters_local_identity_without_dropping_external_or_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = GatewayClient()
    session_key = "agent:main:shared"
    idle = None
    approvals = client.subscribe_global_events({"exec.approval.requested"})

    async def call(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if method == "sessions.messages.subscribe":
            return {"replay_complete": True, "current_stream_seq": 0}
        if method == "sessions.send":
            assert params is not None
            local_message_id = str(params["client_message_id"])
            client._publish_event(  # noqa: SLF001
                {
                    "type": "event",
                    "event": "session.event.text_delta",
                    "payload": {
                        "session_key": session_key,
                        "stream_seq": 1,
                        "turn_id": "turn-web",
                        "client_message_id": "message-web",
                        "surface_id": "web:other",
                        "text": "external",
                    },
                }
            )
            client._publish_event(  # noqa: SLF001
                {
                    "type": "event",
                    "event": "exec.approval.requested",
                    "payload": {"approval_id": "approval-web", "session_key": session_key},
                }
            )
            client._publish_event(  # noqa: SLF001
                {
                    "type": "event",
                    "event": "session.event.done",
                    "payload": {
                        "session_key": session_key,
                        "stream_seq": 2,
                        "turn_id": "turn-local",
                        "client_message_id": local_message_id,
                        "surface_id": client.surface_id,
                    },
                }
            )
            return {
                "turn_id": "turn-local",
                "client_message_id": local_message_id,
                "surface_id": client.surface_id,
            }
        return {}

    monkeypatch.setattr(client, "_call", call)
    idle = await client.subscribe_session_events(session_key)

    events = [event async for event in client.send_message(session_key, "hello")]

    assert [event["event"] for event in events] == ["session.event.done"]
    assert (await idle.get())["payload"]["text"] == "external"
    assert (await approvals.get())["payload"]["approval_id"] == "approval-web"
    await idle.close()
    await approvals.close()


@pytest.mark.asyncio
async def test_send_message_preserves_tui_client_message_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.cli.tui.backend.input_identity import (
        tui_input_identity_scope,
        tui_turn_identity_sink_scope,
    )

    client = GatewayClient()
    session_key = "agent:main:tui-identity"
    sent_params: dict[str, Any] = {}
    bound: list[tuple[str, str]] = []

    async def call(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if method == "sessions.messages.subscribe":
            return {"replay_complete": True, "current_stream_seq": 0}
        if method == "sessions.send":
            assert params is not None
            sent_params.update(params)
            client._publish_event(  # noqa: SLF001
                {
                    "type": "event",
                    "event": "session.event.done",
                    "payload": {
                        "session_key": session_key,
                        "turn_id": "turn-durable",
                        "client_message_id": params["client_message_id"],
                        "surface_id": client.surface_id,
                    },
                }
            )
            return {
                "turn_id": "turn-durable",
                "client_message_id": params["client_message_id"],
                "surface_id": client.surface_id,
            }
        return {}

    async def bind(turn_id: str, client_message_id: str) -> None:
        bound.append((turn_id, client_message_id))

    monkeypatch.setattr(client, "_call", call)
    with tui_input_identity_scope("client-from-composer"):
        with tui_turn_identity_sink_scope(bind):
            events = [event async for event in client.send_message(session_key, "hello")]

    assert [event["event"] for event in events] == ["session.event.done"]
    assert sent_params["client_message_id"] == "client-from-composer"
    assert sent_params["_source"]["client_message_id"] == "client-from-composer"
    assert bound == [("turn-durable", "client-from-composer")]


@pytest.mark.asyncio
async def test_connection_failure_wakes_every_subscription() -> None:
    client = GatewayClient()
    global_events = client.subscribe_global_events({"exec.approval.resolved"})

    client._mark_connection_failed(RuntimeError("socket gone"))  # noqa: SLF001

    with pytest.raises(ConnectionError, match="Gateway connection lost"):
        await global_events.get()


@pytest.mark.asyncio
async def test_late_turn_subscription_replays_client_backlog_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = GatewayClient()
    session_key = "agent:main:shared"
    monkeypatch.setattr(
        client,
        "_call",
        AsyncMock(return_value={"replay_complete": True, "current_stream_seq": 0}),
    )
    discovery = await client.subscribe_session_events(session_key)

    def publish(seq: int, event: str) -> None:
        client._publish_event(  # noqa: SLF001
            {
                "type": "event",
                "event": event,
                "payload": {
                    "session_key": session_key,
                    "stream_seq": seq,
                    "turn_id": "turn-web",
                    "client_message_id": "client-web",
                    "surface_id": "web:browser",
                },
            }
        )

    publish(1, "session.event.text_delta")
    publish(2, "session.event.tool_use_start")
    turn = await client.subscribe_session_events(session_key, since_stream_seq=1)
    turn.bind_turn(turn_id="turn-web", client_message_id="client-web")

    assert (await turn.get())["payload"]["stream_seq"] == 2
    publish(3, "session.event.done")
    assert (await turn.get())["payload"]["stream_seq"] == 3
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(turn.get(), timeout=0.01)

    await turn.close()
    await discovery.close()


@pytest.mark.asyncio
async def test_subscription_exposes_server_replay_gap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = GatewayClient()
    monkeypatch.setattr(
        client,
        "_call",
        AsyncMock(
            return_value={
                "replay_complete": False,
                "replay_gap_reason": "buffer_window_missed",
                "current_stream_seq": 42,
            }
        ),
    )

    subscription = await client.subscribe_session_events(
        "agent:main:gap",
        since_stream_seq=3,
    )

    assert subscription.needs_resync is True
    assert subscription.gap_reason == "buffer_window_missed"
    await subscription.close()
