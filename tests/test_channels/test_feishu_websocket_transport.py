from __future__ import annotations

import asyncio
import sys
import threading
import time
import types
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import pytest

from opensquilla.channels.feishu import FeishuChannel, FeishuChannelConfig, FeishuWebSocketTransport
from opensquilla.channels.transports import InboundEventEnvelope


class _Builder:
    instances: list[_Builder] = []

    def __init__(self) -> None:
        self.registered: dict[str, Callable[[Any], None]] = {}
        _Builder.instances.append(self)

    def register_p2_im_message_receive_v1(self, callback: Callable[[Any], None]) -> _Builder:
        self.message_callback = callback
        self.registered["im.message.receive_v1"] = callback
        return self

    def register_p2_im_message_message_read_v1(self, callback: Callable[[Any], None]) -> _Builder:
        self.read_callback = callback
        self.registered["im.message.message_read_v1"] = callback
        return self

    def register_p2_im_chat_member_bot_added_v1(self, callback: Callable[[Any], None]) -> _Builder:
        self.registered["im.chat.member.bot.added_v1"] = callback
        return self

    def register_p2_im_chat_member_bot_deleted_v1(
        self, callback: Callable[[Any], None]
    ) -> _Builder:
        self.registered["im.chat.member.bot.deleted_v1"] = callback
        return self

    def register_p2_im_message_reaction_created_v1(
        self, callback: Callable[[Any], None]
    ) -> _Builder:
        self.registered["im.message.reaction.created_v1"] = callback
        return self

    def register_p2_im_message_reaction_deleted_v1(
        self, callback: Callable[[Any], None]
    ) -> _Builder:
        self.registered["im.message.reaction.deleted_v1"] = callback
        return self

    def register_p2_card_action_trigger(self, callback: Callable[[Any], None]) -> _Builder:
        self.registered["card.action.trigger"] = callback
        return self

    def build(self) -> object:
        return object()


def _install_fake_lark_module(monkeypatch: pytest.MonkeyPatch) -> tuple[types.ModuleType, type]:
    sdk_module = types.ModuleType("_fake_lark_ws_client")
    sdk_module.loop = None
    sys.modules[sdk_module.__name__] = sdk_module
    _Builder.instances.clear()

    async def _select_forever() -> None:
        while True:
            await asyncio.sleep(3600)

    class FakeClient:
        instances: list[FakeClient] = []

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.args = args
            self.kwargs = kwargs
            self.disconnect_called = False
            self.started = False
            self.start_loop: asyncio.AbstractEventLoop | None = None
            FakeClient.instances.append(self)

        def start(self) -> None:
            loop = sdk_module.loop
            assert isinstance(loop, asyncio.AbstractEventLoop)
            self.start_loop = loop
            self.started = True
            loop.run_until_complete(_select_forever())

        async def _disconnect(self) -> None:
            self.disconnect_called = True

    FakeClient.__module__ = sdk_module.__name__
    sdk_module.Client = FakeClient

    fake_lark = types.SimpleNamespace(
        EventDispatcherHandler=types.SimpleNamespace(builder=lambda *_args: _Builder()),
        FEISHU_DOMAIN="https://open.feishu.cn",
        LARK_DOMAIN="https://open.larksuite.com",
        LogLevel=types.SimpleNamespace(INFO="info"),
        ws=types.SimpleNamespace(Client=FakeClient),
    )
    monkeypatch.setattr("opensquilla.channels.feishu._import_lark_oapi", lambda: fake_lark)
    return sdk_module, FakeClient


async def _noop_handler(_event: Any) -> None:
    return None


async def _wait_until(predicate: Callable[[], bool], timeout: float = 1.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition was not met before timeout")


@pytest.mark.asyncio
async def test_feishu_websocket_stop_stops_sdk_loop_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sdk_module, fake_client = _install_fake_lark_module(monkeypatch)
    transport = FeishuWebSocketTransport(
        FeishuChannelConfig(app_id="app", app_secret="secret", connection_mode="websocket")
    )

    await transport.start(_noop_handler)
    await _wait_until(lambda: bool(fake_client.instances and fake_client.instances[-1].started))

    client = fake_client.instances[-1]
    assert client.start_loop is sdk_module.loop
    assert client.args[:2] == ("app", "secret")

    await transport.stop()

    assert client.disconnect_called is True
    assert transport._thread is None


@pytest.mark.asyncio
async def test_feishu_websocket_registers_supported_non_message_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_lark_module(monkeypatch)
    transport = FeishuWebSocketTransport(
        FeishuChannelConfig(app_id="app", app_secret="secret", connection_mode="websocket")
    )

    await transport.start(_noop_handler)
    await transport.stop()

    assert _Builder.instances
    assert set(_Builder.instances[-1].registered) == {
        "im.message.receive_v1",
        "im.message.message_read_v1",
        "im.chat.member.bot.added_v1",
        "im.chat.member.bot.deleted_v1",
        "im.message.reaction.created_v1",
        "im.message.reaction.deleted_v1",
        "card.action.trigger",
    }


@pytest.mark.asyncio
async def test_feishu_websocket_rejects_second_concurrent_sdk_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_lark_module(monkeypatch)
    first = FeishuWebSocketTransport(
        FeishuChannelConfig(app_id="app-1", app_secret="secret", connection_mode="websocket")
    )
    second = FeishuWebSocketTransport(
        FeishuChannelConfig(app_id="app-2", app_secret="secret", connection_mode="websocket")
    )

    await first.start(_noop_handler)
    try:
        with pytest.raises(RuntimeError, match="only one Feishu websocket"):
            await second.start(_noop_handler)
    finally:
        await first.stop()

    await second.start(_noop_handler)
    await second.stop()


@pytest.mark.asyncio
async def test_feishu_websocket_stop_releases_singleton_after_worker_thread_exits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_lark_module(monkeypatch)
    first = FeishuWebSocketTransport(
        FeishuChannelConfig(app_id="app-1", app_secret="secret", connection_mode="websocket")
    )
    second = FeishuWebSocketTransport(
        FeishuChannelConfig(app_id="app-2", app_secret="secret", connection_mode="websocket")
    )

    first._register_active_client()
    dead_thread = threading.Thread(target=lambda: None)
    dead_thread.start()
    dead_thread.join()
    first._thread = dead_thread
    await first.stop()

    await second.start(_noop_handler)
    await second.stop()


class _FakeTransport:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    async def start(self, _handler: Callable[[Any], Awaitable[None]]) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def health_check(self) -> object:
        return object()


@pytest.mark.asyncio
async def test_feishu_websocket_start_does_not_block_on_bot_info(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    channel = FeishuChannel(
        FeishuChannelConfig(app_id="app", app_secret="secret", connection_mode="websocket")
    )
    transport = _FakeTransport()
    channel._transport = transport  # type: ignore[assignment]

    async def slow_token() -> str:
        await asyncio.sleep(3600)
        return "tenant-token"

    monkeypatch.setattr(channel, "_get_token", slow_token)

    await asyncio.wait_for(channel.start(), timeout=0.1)
    await channel.stop()

    assert transport.started is True
    assert transport.stopped is True


@pytest.mark.asyncio
async def test_feishu_websocket_dedupes_replayed_message_event() -> None:
    channel = FeishuChannel(
        FeishuChannelConfig(app_id="app", app_secret="secret", connection_mode="websocket")
    )
    raw_event = {
        "header": {
            "event_id": "evt-duplicate",
            "event_type": "im.message.receive_v1",
        },
        "event": {
            "sender": {"sender_id": {"open_id": "ou_user"}},
            "message": {
                "message_id": "om_1",
                "chat_id": "oc_chat",
                "chat_type": "p2p",
                "message_type": "text",
                "content": '{"text":"draw an image"}',
            },
        },
    }
    envelope = InboundEventEnvelope(
        source="feishu:websocket",
        event_id="evt-duplicate",
        event_type="im.message.receive_v1",
        raw=raw_event,
        received_at=datetime.now(UTC),
    )

    await channel._handle_inbound_event(envelope)
    await channel._handle_inbound_event(envelope)

    assert channel._queue.qsize() == 1
    assert (await channel.receive()).content == "draw an image"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "event_type,raw_event",
    [
        (
            "im.chat.member.bot.added_v1",
            {"event": {"chat_id": "oc_chat", "operator_id": {"open_id": "ou_user"}}},
        ),
        (
            "im.chat.member.bot.deleted_v1",
            {"event": {"chat_id": "oc_chat", "operator_id": {"open_id": "ou_user"}}},
        ),
        (
            "im.message.reaction.created_v1",
            {
                "event": {
                    "message_id": "om_1",
                    "operator_type": "user",
                    "user_id": {"open_id": "ou_user"},
                    "reaction_type": {"emoji_type": "OK"},
                }
            },
        ),
        (
            "im.message.reaction.deleted_v1",
            {
                "event": {
                    "message_id": "om_1",
                    "operator_type": "user",
                    "user_id": {"open_id": "ou_user"},
                    "reaction_type": {"emoji_type": "OK"},
                }
            },
        ),
        (
            "card.action.trigger",
            {"event": {"open_id": "ou_user", "action": {"value": {"action": "noop"}}}},
        ),
    ],
)
async def test_feishu_non_message_events_do_not_start_agent_turns(
    event_type: str,
    raw_event: dict[str, Any],
) -> None:
    channel = FeishuChannel(
        FeishuChannelConfig(app_id="app", app_secret="secret", connection_mode="websocket")
    )
    envelope = InboundEventEnvelope(
        source="feishu:websocket",
        event_id=f"evt-{event_type}",
        event_type=event_type,
        raw={"header": {"event_id": f"evt-{event_type}", "event_type": event_type}, **raw_event},
        received_at=datetime.now(UTC),
    )

    await channel._handle_inbound_event(envelope)

    assert channel._queue.qsize() == 0


@pytest.mark.asyncio
async def test_feishu_clarify_card_action_enqueues_form_submission() -> None:
    channel = FeishuChannel(
        FeishuChannelConfig(app_id="app", app_secret="secret", connection_mode="websocket")
    )
    envelope = InboundEventEnvelope(
        source="feishu:websocket",
        event_id="evt-clarify-card-action",
        event_type="card.action.trigger",
        raw={
            "header": {
                "event_id": "evt-clarify-card-action",
                "event_type": "card.action.trigger",
            },
            "event": {
                "open_id": "ou_user",
                "operator": {"open_id": "ou_operator"},
                "action": {
                    "value": {
                        "opensquilla_action": "clarify_submit",
                        "channel_id": "oc_chat",
                        "run_id": "run-1",
                        "step": "clarify",
                    },
                    "form_value": {
                        "destination": "Tokyo",
                        "days": 5,
                        "include_food": True,
                    },
                },
            },
        },
        received_at=datetime.now(UTC),
    )

    await channel._handle_inbound_event(envelope)

    msg = await channel.receive()
    assert msg.sender_id == "ou_operator"
    assert msg.channel_id == "oc_chat"
    assert "destination: Tokyo" in msg.content
    assert "days: 5" in msg.content
    assert "include_food: true" in msg.content
    assert msg.metadata["conversation_kind"] == "interaction"
    assert msg.metadata["is_group"] is True
    assert msg.metadata["input_provenance"] == "clarify_form"
    assert msg.metadata["clarify_run_id"] == "run-1"


@pytest.mark.asyncio
async def test_feishu_clarify_card_action_preserves_direct_session_type() -> None:
    channel = FeishuChannel(
        FeishuChannelConfig(app_id="app", app_secret="secret", connection_mode="websocket")
    )
    envelope = InboundEventEnvelope(
        source="feishu:websocket",
        event_id="evt-clarify-card-action-dm",
        event_type="card.action.trigger",
        raw={
            "header": {
                "event_id": "evt-clarify-card-action-dm",
                "event_type": "card.action.trigger",
            },
            "event": {
                "open_id": "ou_user",
                "operator": {"open_id": "ou_operator"},
                "action": {
                    "value": {
                        "opensquilla_action": "clarify_submit",
                        "channel_id": "oc_dm",
                        "chat_type": "p2p",
                        "is_group": False,
                        "run_id": "run-1",
                    },
                    "form_value": {"destination": "Tokyo"},
                },
            },
        },
        received_at=datetime.now(UTC),
    )

    await channel._handle_inbound_event(envelope)

    msg = await channel.receive()
    assert msg.sender_id == "ou_operator"
    assert msg.channel_id == "oc_dm"
    assert msg.metadata["is_group"] is False
    assert msg.metadata["chat_type"] == "p2p"
    assert msg.metadata["native_chat_id"] == "oc_dm"
