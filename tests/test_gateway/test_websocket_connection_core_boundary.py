from __future__ import annotations

import importlib


def test_websocket_connection_core_boundary_reexports_public_connection_types() -> None:
    """WebSocket handler module keeps public imports while core lives separately."""
    core = importlib.import_module("opensquilla.gateway.websocket_connection")
    websocket = importlib.import_module("opensquilla.gateway.websocket")

    assert websocket.WsConnection is core.WsConnection
    assert websocket.ConnectionRegistry is core.ConnectionRegistry
    assert websocket._OutboundFrame is core._OutboundFrame
    assert websocket._LOSSY_EVENTS is core._LOSSY_EVENTS
    assert websocket._SENTINEL_STOP is core._SENTINEL_STOP
