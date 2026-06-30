from __future__ import annotations

import asyncio
import json
import sys
from types import SimpleNamespace
from typing import Any

import pytest

from opensquilla.channels.contract import (
    ChannelCapabilities,
    ChannelPlatformCapabilityStatus,
    ChannelPlatformCategories,
)
from opensquilla.channels.registry import parse_channel_entry
from opensquilla.channels.types import OutgoingMessage
from opensquilla.channels.wecom import WeComChannel, WeComChannelConfig
from opensquilla.gateway.config import WeComChannelEntry


class _FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.closed = False
        self._subscribe_acked = False
        self._queue: asyncio.Queue[str] = asyncio.Queue()

    def feed(self, payload: dict[str, Any]) -> None:
        self._queue.put_nowait(json.dumps(payload))

    async def send(self, raw: str) -> None:
        self.sent.append(json.loads(raw))

    async def recv(self) -> str:
        if not self._subscribe_acked and self.sent:
            subscribe = self.sent[0]
            self._subscribe_acked = True
            return json.dumps(
                {
                    "cmd": "aibot_subscribe",
                    "headers": {"req_id": subscribe["headers"]["req_id"]},
                    "errcode": 0,
                }
            )
        return await self._queue.get()

    async def close(self) -> None:
        self.closed = True


def _install_fake_websockets(
    monkeypatch: pytest.MonkeyPatch, ws: _FakeWebSocket
) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def connect(url: str, **kwargs: Any) -> _FakeWebSocket:
        calls.append({"url": url, "kwargs": kwargs})
        return ws

    monkeypatch.setitem(sys.modules, "websockets", SimpleNamespace(connect=connect))
    return calls


@pytest.mark.asyncio
async def test_wecom_websocket_subscribes_to_ai_bot_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ws = _FakeWebSocket()
    calls = _install_fake_websockets(monkeypatch, ws)
    channel = WeComChannel(
        WeComChannelConfig(
            connection_mode="websocket",
            bot_id="bot-id",
            bot_secret="bot-secret",
        )
    )

    await channel.start()
    try:
        assert calls == [
            {
                "url": "wss://openws.work.weixin.qq.com",
                "kwargs": {"ping_interval": 30.0, "ping_timeout": 30.0},
            }
        ]
        assert "wsagent" not in calls[0]["url"]
        assert "access_token" not in calls[0]["url"]
        assert ws.sent[0]["cmd"] == "aibot_subscribe"
        assert ws.sent[0]["body"] == {"bot_id": "bot-id", "secret": "bot-secret"}
    finally:
        await channel.stop()


@pytest.mark.asyncio
async def test_wecom_websocket_inbound_callback_can_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _FakeWebSocket()
    _install_fake_websockets(monkeypatch, ws)
    channel = WeComChannel(
        WeComChannelConfig(
            connection_mode="websocket",
            bot_id="bot-id",
            bot_secret="bot-secret",
        )
    )

    await channel.start()
    try:
        ws.feed(
            {
                "cmd": "aibot_msg_callback",
                "headers": {"req_id": "inbound-1"},
                "body": {
                    "msgid": "msg-1",
                    "chatid": "chat-1",
                    "chattype": "group",
                    "msgtype": "text",
                    "from": {"userid": "user-1"},
                    "text": {"content": "hello"},
                },
            }
        )
        incoming = await asyncio.wait_for(channel.receive(), timeout=1)
        assert incoming.content == "hello"
        assert incoming.channel_id == "chat-1"
        assert incoming.metadata["wecom_protocol"] == "aibot"
        assert incoming.metadata["wecom_req_id"] == "inbound-1"

        send_task = asyncio.create_task(channel.send(OutgoingMessage(content="world")))
        while len(ws.sent) < 2:
            await asyncio.sleep(0)
        assert ws.sent[1] == {
            "cmd": "aibot_respond_msg",
            "headers": {"req_id": "inbound-1"},
            "body": {"msgtype": "markdown", "markdown": {"content": "world"}},
        }
        ws.feed({"cmd": "aibot_respond_msg", "headers": {"req_id": "inbound-1"}, "errcode": 0})
        await asyncio.wait_for(send_task, timeout=1)
    finally:
        await channel.stop()


def test_wecom_websocket_capabilities_do_not_advertise_corp_app_file_upload() -> None:
    channel = WeComChannel(
        WeComChannelConfig(
            connection_mode="websocket",
            bot_id="bot-id",
            bot_secret="bot-secret",
        )
    )

    assert channel.capability_profile.supports(ChannelCapabilities.WEBSOCKET)
    assert not channel.capability_profile.supports(ChannelCapabilities.NATIVE_FILE_UPLOAD)
    assert (
        channel.platform_capability_manifest.get(ChannelPlatformCategories.FILES).status
        == ChannelPlatformCapabilityStatus.UNSUPPORTED
    )


def test_wecom_websocket_config_requires_bot_credentials() -> None:
    with pytest.raises(ValueError, match="bot_id and bot_secret"):
        parse_channel_entry(
            {
                "type": "wecom",
                "name": "wecom",
                "connection_mode": "websocket",
                "corp_id": "corp",
                "corp_secret": "corp-secret",
                "agent_id_int": 1001,
            }
        )

    entry = parse_channel_entry(
        {
            "type": "wecom",
            "name": "wecom",
            "connection_mode": "websocket",
            "bot_id": "bot",
            "bot_secret": "secret",
        }
    )
    assert isinstance(entry, WeComChannelEntry)
    assert entry.websocket_url == "wss://openws.work.weixin.qq.com"


def test_wecom_webhook_config_remains_supported() -> None:
    entry = parse_channel_entry(
        {
            "type": "wecom",
            "name": "wecom-callback",
            "connection_mode": "webhook",
            "corp_id": "corp",
            "corp_secret": "corp-secret",
            "agent_id_int": 1001,
            "token": "token",
            "encoding_aes_key": "abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG",
        }
    )
    assert isinstance(entry, WeComChannelEntry)
    assert entry.connection_mode == "webhook"
