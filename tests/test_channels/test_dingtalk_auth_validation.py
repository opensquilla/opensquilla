from __future__ import annotations

import asyncio
import json
import sys
import types
from typing import Any

import pytest
import requests

from opensquilla.channels.dingtalk import DingTalkChannel, DingTalkChannelConfig


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_dingtalk_start_requires_client_id_and_secret() -> None:
    with pytest.raises(ValueError, match="client_id and client_secret are required"):
        await DingTalkChannel(DingTalkChannelConfig(client_secret="secret")).start()

    with pytest.raises(ValueError, match="client_id and client_secret are required"):
        await DingTalkChannel(DingTalkChannelConfig(client_id="client-id")).start()


@pytest.mark.anyio
async def test_dingtalk_start_builds_stream_client_with_client_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    credentials: list[tuple[str, str]] = []
    clients: list[Any] = []

    class FakeChatbotMessage:
        TOPIC = "chatbot.topic"

        @staticmethod
        def from_dict(data: dict[str, Any]) -> Any:
            return data

    class FakeAckMessage:
        STATUS_OK = "ok"

    class FakeAsyncChatbotHandler:
        def __init__(self) -> None:
            return None

    class FakeCredential:
        def __init__(self, client_id: str, client_secret: str) -> None:
            self.client_id = client_id
            self.client_secret = client_secret
            credentials.append((client_id, client_secret))

    class FakeStreamClient:
        OPEN_CONNECTION_API = "https://api.dingtalk.com/v1.0/gateway/connections/open"

        def __init__(self, credential: FakeCredential) -> None:
            self.credential = credential
            self.handlers: list[tuple[str, Any]] = []
            clients.append(self)

        def register_callback_handler(self, topic: str, handler: Any) -> None:
            self.handlers.append((topic, handler))

        async def start(self) -> None:
            await asyncio.sleep(0)

    fake_module = types.ModuleType("dingtalk_stream")
    setattr(fake_module, "AckMessage", FakeAckMessage)
    setattr(fake_module, "AsyncChatbotHandler", FakeAsyncChatbotHandler)
    setattr(fake_module, "ChatbotMessage", FakeChatbotMessage)
    setattr(fake_module, "Credential", FakeCredential)
    setattr(fake_module, "DingTalkStreamClient", FakeStreamClient)
    monkeypatch.setitem(sys.modules, "dingtalk_stream", fake_module)

    class FakeResponse:
        status_code = 200
        text = '{"endpoint":"wss://example.test","ticket":"ticket"}'

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, str]:
            return {"endpoint": "wss://example.test", "ticket": "ticket"}

    preflight_payloads: list[dict[str, Any]] = []

    def fake_post(url: str, *, headers: dict[str, str], data: bytes, timeout: float) -> Any:
        assert url == FakeStreamClient.OPEN_CONNECTION_API
        assert timeout > 0
        preflight_payloads.append(json.loads(data.decode("utf-8")))
        return FakeResponse()

    monkeypatch.setattr(requests, "post", fake_post)

    channel = DingTalkChannel(
        DingTalkChannelConfig(client_id="client-id", client_secret="client-secret")
    )

    await channel.start()
    await channel.stop()

    assert credentials == [("client-id", "client-secret")]
    assert len(clients) == 1
    assert clients[0].handlers
    assert clients[0].handlers[0][0] == "chatbot.topic"
    assert len(preflight_payloads) == 1
    assert preflight_payloads[0]["clientId"] == "client-id"
    assert preflight_payloads[0]["clientSecret"] == "client-secret"
    assert preflight_payloads[0]["subscriptions"] == [
        {"type": "CALLBACK", "topic": "chatbot.topic"}
    ]
    assert preflight_payloads[0]["ua"].startswith("dingtalk-sdk-python/")


@pytest.mark.anyio
async def test_dingtalk_auth_failed_preflight_raises_structured_diagnostic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clients: list[Any] = []

    class FakeChatbotMessage:
        TOPIC = "chatbot.topic"

        @staticmethod
        def from_dict(data: dict[str, Any]) -> Any:
            return data

    class FakeAckMessage:
        STATUS_OK = "ok"

    class FakeAsyncChatbotHandler:
        def __init__(self) -> None:
            return None

    class FakeCredential:
        def __init__(self, client_id: str, client_secret: str) -> None:
            self.client_id = client_id
            self.client_secret = client_secret

    class FakeStreamClient:
        OPEN_CONNECTION_API = "https://api.dingtalk.com/v1.0/gateway/connections/open"

        def __init__(self, credential: FakeCredential) -> None:
            clients.append(self)

        def register_callback_handler(self, topic: str, handler: Any) -> None:
            raise AssertionError("SDK client should not register callbacks after auth failure")

        async def start(self) -> None:
            raise AssertionError("SDK loop should not start after auth failure")

    fake_module = types.ModuleType("dingtalk_stream")
    setattr(fake_module, "AckMessage", FakeAckMessage)
    setattr(fake_module, "AsyncChatbotHandler", FakeAsyncChatbotHandler)
    setattr(fake_module, "ChatbotMessage", FakeChatbotMessage)
    setattr(fake_module, "Credential", FakeCredential)
    setattr(fake_module, "DingTalkStreamClient", FakeStreamClient)
    monkeypatch.setitem(sys.modules, "dingtalk_stream", fake_module)

    class FakeResponse:
        status_code = 401
        text = '{"code":"authFailed","message":"鉴权失败"}'

        def raise_for_status(self) -> None:
            raise requests.HTTPError("401 Client Error: Unauthorized")

        def json(self) -> dict[str, str]:
            return {"code": "authFailed", "message": "鉴权失败"}

    monkeypatch.setattr(
        requests,
        "post",
        lambda *args, **kwargs: FakeResponse(),
    )

    channel = DingTalkChannel(
        DingTalkChannelConfig(client_id="bad-client", client_secret="super-secret")
    )

    with pytest.raises(RuntimeError, match="DingTalk credentials were rejected") as exc:
        await channel.start()

    diagnostic = getattr(exc.value, "diagnostic", {})
    assert diagnostic["error_class"] == "auth_invalid"
    assert diagnostic["provider_code"] == "authFailed"
    assert diagnostic["retryable"] is False
    assert "AppKey/AppSecret" in diagnostic["message"]
    assert "super-secret" not in str(diagnostic)
    assert clients == []
    assert channel._run_task is None
