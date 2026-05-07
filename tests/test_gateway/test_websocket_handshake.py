from __future__ import annotations

from types import SimpleNamespace

import pytest
from starlette.websockets import WebSocketDisconnect, WebSocketState

from opensquilla.gateway.config import GatewayConfig
from opensquilla.gateway.websocket import handle_ws_connection


class _DisconnectingChallengeWebSocket:
    client_state = WebSocketState.CONNECTED
    client = SimpleNamespace(host="127.0.0.1", port=12345)

    def __init__(self) -> None:
        self.accepted = False

    async def accept(self) -> None:
        self.accepted = True

    async def send_text(self, _text: str) -> None:
        raise WebSocketDisconnect(code=1006)


@pytest.mark.asyncio
async def test_websocket_handshake_ignores_disconnect_while_sending_challenge() -> None:
    ws = _DisconnectingChallengeWebSocket()

    await handle_ws_connection(ws, GatewayConfig(), dispatcher=object())

    assert ws.accepted is True
