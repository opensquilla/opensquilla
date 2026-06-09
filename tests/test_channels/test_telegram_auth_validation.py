from __future__ import annotations

import json
from typing import Any

import pytest
from starlette.requests import Request

from opensquilla.channels.telegram import TelegramChannel, TelegramChannelConfig


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
                    "edited_message",
                    "channel_post",
                    "edited_channel_post",
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
