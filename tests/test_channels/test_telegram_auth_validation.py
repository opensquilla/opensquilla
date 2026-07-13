from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from starlette.requests import Request

from opensquilla.channels.telegram import (
    TelegramApiError,
    TelegramChannel,
    TelegramChannelConfig,
)
from opensquilla.channels.types import IngressVerification


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class RecordingTelegramChannel(TelegramChannel):
    def __init__(self, config: TelegramChannelConfig) -> None:
        super().__init__(config)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def _api(self, method: str, payload: dict[str, Any] | None = None) -> Any:
        self.calls.append((method, payload or {}))
        if method == "getMe":
            return {"id": 12345, "username": "opensquilla_test_bot"}
        return True


@pytest.mark.anyio
async def test_webhook_start_validates_token_with_get_me_then_sets_secret_token() -> None:
    channel = RecordingTelegramChannel(
        TelegramChannelConfig(
            token="bot-token",
            transport_name="webhook",
            webhook_url="https://example.test/telegram/events",
            webhook_secret_token="secret-token",
            drop_pending_updates=True,
        )
    )

    await channel.start()

    assert channel.bot_user_id == "12345"
    assert channel.bot_username == "opensquilla_test_bot"
    assert channel.calls == [
        ("getMe", {}),
        (
            "setWebhook",
            {
                "url": "https://example.test/telegram/events",
                "drop_pending_updates": True,
                "allowed_updates": [
                    "message",
                    "channel_post",
                ],
                "secret_token": "secret-token",
            },
        ),
    ]


@pytest.mark.anyio
async def test_webhook_mode_requires_url_and_secret_token() -> None:
    with pytest.raises(ValueError, match="webhook_url is required"):
        await RecordingTelegramChannel(
            TelegramChannelConfig(
                token="bot-token",
                transport_name="webhook",
                webhook_secret_token="secret-token",
            )
        ).start()

    with pytest.raises(ValueError, match="webhook_secret_token is required"):
        await RecordingTelegramChannel(
            TelegramChannelConfig(
                token="bot-token",
                transport_name="webhook",
                webhook_url="https://example.test/telegram/events",
            )
        ).start()


async def _webhook_response(
    channel: TelegramChannel,
    *,
    secret_header: str | None,
    body: dict[str, Any],
):
    headers: list[tuple[bytes, bytes]] = [(b"content-type", b"application/json")]
    if secret_header is not None:
        headers.append((b"x-telegram-bot-api-secret-token", secret_header.encode()))
    raw = json.dumps(body).encode()
    scope = {
        "type": "http",
        "method": "POST",
        "path": channel.config.webhook_path,
        "headers": headers,
        "query_string": b"",
    }

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": raw, "more_body": False}

    request = Request(scope, receive)
    return await channel._handle_webhook(request)


@pytest.mark.anyio
async def test_webhook_rejects_missing_or_wrong_secret_header() -> None:
    channel = TelegramChannel(
        TelegramChannelConfig(
            token="bot-token",
            transport_name="webhook",
            webhook_url="https://example.test/telegram/events",
            webhook_secret_token="expected-secret",
        )
    )

    missing = await _webhook_response(channel, secret_header=None, body={})
    wrong = await _webhook_response(channel, secret_header="wrong-secret", body={})

    assert missing.status_code == 401
    assert wrong.status_code == 401


@pytest.mark.anyio
async def test_webhook_accepts_matching_secret_header() -> None:
    channel = TelegramChannel(
        TelegramChannelConfig(
            token="bot-token",
            transport_name="webhook",
            webhook_url="https://example.test/telegram/events",
            webhook_secret_token="expected-secret",
        )
    )

    response = await _webhook_response(
        channel,
        secret_header="expected-secret",
        body={"update_id": 1, "unknown": {}},
    )

    assert response.status_code == 200


@pytest.mark.anyio
async def test_webhook_message_carries_authenticated_provenance_and_reply_target() -> None:
    channel = TelegramChannel(
        TelegramChannelConfig(
            name="telegram-main",
            token="bot-token",
            transport_name="webhook",
            webhook_url="https://example.test/telegram/events",
            webhook_secret_token="expected-secret",
        )
    )

    response = await _webhook_response(
        channel,
        secret_header="expected-secret",
        body={
            "update_id": 12,
            "message": {
                "message_id": 34,
                "from": {"id": 56},
                "chat": {"id": 78, "type": "private"},
                "text": "hello",
            },
        },
    )
    message = await channel.receive()
    reply = channel.build_reply_message("world", message)

    assert response.status_code == 200
    assert message.provenance.verification == IngressVerification.WEBHOOK_TOKEN
    assert message.provenance.principal is not None
    assert message.provenance.principal.subject_id == "56"
    assert message.provenance.event_id == "12"
    assert reply.metadata["reply_to_message_id"] == "34"


def test_edited_message_is_not_normalized_as_a_new_turn() -> None:
    channel = TelegramChannel(TelegramChannelConfig(token="bot-token"))

    with pytest.raises(ValueError, match="edited updates"):
        channel.parse_incoming(
            {
                "update_id": 1,
                "edited_message": {
                    "message_id": 2,
                    "from": {"id": 3},
                    "chat": {"id": 4, "type": "private"},
                    "text": "edited",
                },
            }
        )


@pytest.mark.anyio
async def test_api_error_preserves_telegram_retry_after() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            json={
                "ok": False,
                "error_code": 429,
                "description": "Too Many Requests",
                "parameters": {"retry_after": 7},
            },
        )

    channel = TelegramChannel(TelegramChannelConfig(token="bot-token"))
    channel._client = httpx.AsyncClient(
        base_url="https://api.telegram.org",
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(TelegramApiError) as raised:
            await channel._api("sendMessage", {"chat_id": 1, "text": "hello"})
    finally:
        await channel.stop()

    assert raised.value.error_code == 429
    assert raised.value.retry_after == 7


@pytest.mark.anyio
async def test_typing_and_reaction_use_current_bot_api_methods() -> None:
    channel = RecordingTelegramChannel(
        TelegramChannelConfig(token="bot-token", default_chat_id="123")
    )

    typing = await channel.send_typing()
    reaction = await channel.set_reaction("123", 45, "👍")

    assert typing.is_delivered()
    assert reaction.is_delivered()
    assert channel.calls == [
        ("sendChatAction", {"chat_id": "123", "action": "typing"}),
        (
            "setMessageReaction",
            {
                "chat_id": 123,
                "message_id": 45,
                "reaction": [{"type": "emoji", "emoji": "👍"}],
            },
        ),
    ]
