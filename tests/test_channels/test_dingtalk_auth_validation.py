from __future__ import annotations

import asyncio
import sys
import types
from typing import Any

import pytest

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

    channel = DingTalkChannel(
        DingTalkChannelConfig(client_id="client-id", client_secret="client-secret")
    )

    await channel.start()
    await channel.stop()

    assert credentials == [("client-id", "client-secret")]
    assert len(clients) == 1
    assert clients[0].handlers
    assert clients[0].handlers[0][0] == "chatbot.topic"
