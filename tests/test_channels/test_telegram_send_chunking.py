from __future__ import annotations

import json

import httpx

from opensquilla.channels._util import split_text_for_channel
from opensquilla.channels.telegram import TelegramChannel, TelegramChannelConfig
from opensquilla.channels.types import OutgoingMessage

_API_LIMIT = 4096


def _make_channel(delivered: list[str]) -> TelegramChannel:
    def handler(request: httpx.Request) -> httpx.Response:
        if not request.url.path.endswith("/sendMessage"):
            return httpx.Response(200, json={"ok": True, "result": {}})
        text = json.loads(request.content.decode()).get("text", "")
        if len(text) > _API_LIMIT:
            return httpx.Response(
                400,
                json={
                    "ok": False,
                    "error_code": 400,
                    "description": "Bad Request: message is too long",
                },
            )
        delivered.append(text)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": len(delivered)}})

    channel = TelegramChannel(TelegramChannelConfig(token="test-token", default_chat_id="12345"))
    channel._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.telegram.org"
    )
    return channel


async def test_telegram_send_splits_long_text_under_api_limit() -> None:
    delivered: list[str] = []
    channel = _make_channel(delivered)

    long_text = "A" * 6000
    await channel.send(OutgoingMessage(content=long_text, metadata={"chat_id": "12345"}))

    assert len(delivered) >= 2
    assert all(len(part) <= _API_LIMIT for part in delivered)
    assert "".join(delivered) == long_text


async def test_telegram_send_keeps_short_text_as_single_message() -> None:
    delivered: list[str] = []
    channel = _make_channel(delivered)

    await channel.send(OutgoingMessage(content="short", metadata={"chat_id": "12345"}))

    assert delivered == ["short"]


def test_channel_splitter_preserves_whitespace_at_preferred_boundaries() -> None:
    text = "aa\n\nbbb\ncccc dddd"

    chunks = split_text_for_channel(text, 5)

    assert all(len(chunk) <= 5 for chunk in chunks)
    assert "".join(chunks) == text
