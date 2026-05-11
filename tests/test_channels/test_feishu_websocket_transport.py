from __future__ import annotations

import asyncio
import sys
import time
import types
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import pytest

from opensquilla.channels.feishu import FeishuChannel, FeishuChannelConfig, FeishuWebSocketTransport
from opensquilla.channels.transports import InboundEventEnvelope


class _Builder:
    def register_p2_im_message_receive_v1(self, callback: Callable[[Any], None]) -> _Builder:
        self.message_callback = callback
        return self

    def register_p2_im_message_message_read_v1(self, callback: Callable[[Any], None]) -> _Builder:
        self.read_callback = callback
        return self

    def build(self) -> object:
        return object()


def _install_fake_lark_module(monkeypatch: pytest.MonkeyPatch) -> tuple[types.ModuleType, type]:
    sdk_module = types.ModuleType("_fake_lark_ws_client")
    sdk_module.loop = None
    sys.modules[sdk_module.__name__] = sdk_module

    async def _select_forever() -> None:
        while True:
            await asyncio.sleep(3600)

    class FakeClient:
        instances: list[FakeClient] = []

        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
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

    await transport.stop()

    assert client.disconnect_called is True
    assert transport._thread is None


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
