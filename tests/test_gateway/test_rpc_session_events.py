from __future__ import annotations

from types import SimpleNamespace

import pytest

from opensquilla.gateway.rpc_session_events import (
    buffer_session_event,
    emit_to_session_subscribers,
    optional_stream_seq,
)
from opensquilla.gateway.session_streams import SessionStreamRegistry


def test_optional_stream_seq_accepts_snake_and_camel_aliases() -> None:
    assert optional_stream_seq({"since_stream_seq": "7"}) == 7
    assert optional_stream_seq({"sinceStreamSeq": 3}) == 3
    assert optional_stream_seq({"since_stream_seq": -4}) == 0
    assert optional_stream_seq({"since_stream_seq": "bad"}) is None
    assert optional_stream_seq(None) is None


def test_buffer_session_event_records_only_session_events() -> None:
    registry = SessionStreamRegistry(max_events_per_session=5)
    key = "agent:main:event-boundary"

    event_payload = buffer_session_event(
        key,
        "session.event.text_delta",
        {"text": "hello"},
        stream_registry=registry,
    )
    changed_payload = buffer_session_event(
        key,
        "sessions.changed",
        {"reason": "turn_complete"},
        stream_registry=registry,
    )

    assert event_payload == {
        "text": "hello",
        "session_key": key,
        "stream_seq": 1,
    }
    assert changed_payload == {"reason": "turn_complete"}
    assert registry.current_seq(key) == 1


@pytest.mark.asyncio
async def test_emit_to_session_subscribers_injects_epoch_and_buffers_session_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[tuple[str, dict]] = []
    key = "agent:main:event-emit"

    class FakeConn:
        async def send_event(self, event_name: str, payload: dict) -> None:
            sent.append((event_name, payload))

    class FakeRegistry:
        def get(self, conn_id: str) -> FakeConn | None:
            return FakeConn() if conn_id == "conn-1" else None

    class FakeSubMgr:
        def get_message_subscribers(self, session_key: str) -> set[str]:
            return {"conn-1"} if session_key == key else set()

        def get_session_subscribers(self) -> set[str]:
            return set()

    class FakeStorage:
        async def get_epoch(self, session_key: str) -> int:
            assert session_key == key
            return 4

    class FakeSessionManager:
        storage = FakeStorage()

        def __init__(self) -> None:
            self.epochs: dict[str, int] = {}

        def get_cached_epoch(self, session_key: str) -> int | None:
            return self.epochs.get(session_key)

        def set_cached_epoch(self, session_key: str, epoch: int) -> None:
            self.epochs[session_key] = epoch

    import opensquilla.gateway.websocket as websocket

    monkeypatch.setattr(websocket, "get_registry", lambda: FakeRegistry())

    session_manager = FakeSessionManager()
    stream_registry = SessionStreamRegistry(max_events_per_session=5)
    ctx = SimpleNamespace(
        subscription_manager=FakeSubMgr(),
        session_manager=session_manager,
    )

    await emit_to_session_subscribers(
        ctx,
        key,
        "session.event.done",
        {"reason": "stop"},
        stream_registry=stream_registry,
    )

    assert session_manager.epochs == {key: 4}
    assert sent == [
        (
            "session.event.done",
            {
                "reason": "stop",
                "epoch": 4,
                "session_key": key,
                "stream_seq": 1,
            },
        )
    ]
