"""Slack Socket Mode transport, auto-target replies, and self-echo filtering."""

from __future__ import annotations

from typing import Any

import pytest

from opensquilla.channels.slack import SlackAuthError, SlackChannel
from opensquilla.channels.types import IncomingMessage, OutgoingMessage


def _mk(**kwargs: Any) -> SlackChannel:
    kwargs.setdefault("slack_channel_id", "")
    ch = SlackChannel(token="xoxb-test", **kwargs)
    ch.bot_user_id = "UBOT"
    return ch


class _FakeResp:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    async def post(
        self, path: str, json: dict[str, Any] | None = None, headers: Any = None
    ) -> _FakeResp:
        self.calls.append((path, json))
        if path == "/auth.test":
            return _FakeResp({"ok": True, "user_id": "UBOT"})
        return _FakeResp({"ok": True, "ts": "1700000000.000100"})


# ── transport selection ───────────────────────────────────────────────────


def test_transport_name_follows_connection_mode() -> None:
    assert _mk().transport_name == "webhook"
    assert _mk(connection_mode="socket").transport_name == "websocket"


async def test_socket_mode_requires_app_token() -> None:
    ch = _mk(connection_mode="socket")  # no app_token
    ch._get_client = lambda: _FakeClient()  # type: ignore[method-assign]
    with pytest.raises(SlackAuthError):
        await ch.start()


# ── inbound filtering (the self-echo / loop guard) ─────────────────────────


def test_ingest_accepts_plain_user_message() -> None:
    ch = _mk()
    ch._ingest_event_callback(
        {
            "event_id": "Ev1",
            "event": {
                "type": "message",
                "user": "UUSER",
                "channel": "D123",
                "text": "hi",
                "ts": "1.1",
            },
        }
    )
    assert ch._queue.qsize() == 1
    msg = ch._queue.get_nowait()
    assert msg.channel_id == "D123"
    assert msg.content == "hi"


@pytest.mark.parametrize(
    "event",
    [
        {"type": "message", "bot_id": "B1", "channel": "D1", "text": "x", "ts": "2"},
        {"type": "message", "user": "UBOT", "channel": "D1", "text": "x", "ts": "3"},
        {"type": "message", "subtype": "bot_message", "channel": "D1", "text": "x", "ts": "4"},
        {"type": "message", "subtype": "message_changed", "channel": "D1", "ts": "5"},
        {"type": "message", "subtype": "message_deleted", "channel": "D1", "ts": "6"},
    ],
)
def test_ingest_drops_self_echoes_and_non_user_subtypes(event: dict[str, Any]) -> None:
    ch = _mk()
    ch._ingest_event_callback({"event_id": f"e-{event.get('ts')}", "event": event})
    assert ch._queue.qsize() == 0


def test_ingest_dedupes_replayed_event() -> None:
    ch = _mk()
    payload = {
        "event_id": "Dup1",
        "event": {"type": "message", "user": "U", "channel": "D1", "text": "hi", "ts": "9"},
    }
    ch._ingest_event_callback(payload)
    ch._ingest_event_callback(payload)
    assert ch._queue.qsize() == 1


# ── outbound: auto-target the originating conversation ─────────────────────


async def test_send_auto_targets_reply_conversation() -> None:
    ch = _mk()  # slack_channel_id empty on purpose
    fake = _FakeClient()
    ch._get_client = lambda: fake  # type: ignore[method-assign]
    await ch.send(OutgoingMessage(content="hello", reply_to="D999"))
    post = next(c for c in fake.calls if c[0] == "/chat.postMessage")
    assert post[1] is not None
    assert post[1]["channel"] == "D999"
    # A conversation id must NOT be misused as a thread anchor.
    assert "thread_ts" not in post[1]


async def test_send_threads_only_on_message_ts() -> None:
    ch = _mk(slack_channel_id="C1")
    fake = _FakeClient()
    ch._get_client = lambda: fake  # type: ignore[method-assign]
    await ch.send(OutgoingMessage(content="hi", reply_to="1700000000.000200"))
    post = next(c for c in fake.calls if c[0] == "/chat.postMessage")
    assert post[1] is not None
    assert post[1]["channel"] == "C1"
    assert post[1]["thread_ts"] == "1700000000.000200"


def test_reply_helpers_target_inbound_conversation() -> None:
    ch = _mk()
    inbound = IncomingMessage(sender_id="U", channel_id="D42", content="hi")
    assert ch.build_reply_message("r", inbound).reply_to == "D42"
    assert ch.streaming_reply_kwargs(inbound) == {"channel": "D42"}
