from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from opensquilla.channels.rpc_payload import (
    channel_logout_rpc_payload,
    channel_restart_rpc_payload,
    channel_status_rpc_payload,
)

ROOT = Path(__file__).resolve().parents[2]
RPC_CHANNELS = ROOT / "src/opensquilla/gateway/rpc_channels.py"


class FakeChannelManager:
    def __init__(self, health_map: dict[str, Any] | None = None) -> None:
        self._health_map = health_map or {}
        self._channel_types = {"runtime": "slack"}
        self.stopped: list[str] = []
        self.restarted: list[str] = []

    async def health(self) -> dict[str, Any]:
        return self._health_map

    def get(self, name: str) -> object | None:
        return object() if name in {"runtime", "configured"} else None

    async def stop_channel(self, name: str) -> None:
        self.stopped.append(name)

    async def restart_channel(self, name: str) -> None:
        self.restarted.append(name)


def _config(entries: list[dict[str, Any]]) -> Any:
    return SimpleNamespace(channels=SimpleNamespace(channels=entries))


def _health(
    *,
    connected: bool,
    bot_user_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> Any:
    return SimpleNamespace(connected=connected, bot_user_id=bot_user_id, extra=extra or {})


def _imports_from(path: Path) -> set[tuple[str, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                imports.add((node.module, alias.name))
    return imports


def _top_level_functions(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


@pytest.mark.asyncio
async def test_channel_status_rpc_payload_merges_config_and_runtime_health() -> None:
    manager = FakeChannelManager(
        {
            "configured": _health(
                connected=True,
                bot_user_id="bot-1",
                extra={"connected_since": "now", "restart_attempts": 2},
            ),
            "runtime": _health(
                connected=False,
                extra={"dispatch_state": "dead", "restart_attempts": 4},
            ),
        }
    )

    payload = await channel_status_rpc_payload(
        _config(
            [
                {"name": "configured", "type": "slack", "enabled": True},
                {"name": "disabled", "type": "feishu", "enabled": False},
            ]
        ),
        manager,
    )

    assert payload == {
        "channels": [
            {
                "name": "configured",
                "connected": True,
                "status": "connected",
                "bot_user_id": "bot-1",
                "connected_since": "now",
                "restart_attempts": 2,
                "type": "slack",
                "enabled": True,
                "configured": True,
            },
            {
                "name": "disabled",
                "connected": False,
                "status": "disabled",
                "bot_user_id": None,
                "connected_since": None,
                "restart_attempts": 0,
                "type": "feishu",
                "enabled": False,
                "configured": True,
            },
            {
                "name": "runtime",
                "connected": False,
                "status": "dead",
                "bot_user_id": None,
                "connected_since": None,
                "restart_attempts": 4,
                "type": "slack",
                "enabled": True,
                "configured": False,
            },
        ]
    }


@pytest.mark.asyncio
async def test_channel_lifecycle_rpc_payloads_parse_names_and_preserve_wire_shape() -> None:
    manager = FakeChannelManager()

    logout = await channel_logout_rpc_payload({"name": "runtime"}, manager)
    restart = await channel_restart_rpc_payload({"channel": "runtime"}, manager)

    assert logout == {"status": "disconnected", "channel": "runtime"}
    assert restart == {"status": "restarted", "channel": "runtime"}
    assert manager.stopped == ["runtime"]
    assert manager.restarted == ["runtime"]


@pytest.mark.asyncio
async def test_channel_lifecycle_rpc_payloads_validate_missing_channels() -> None:
    manager = FakeChannelManager()

    with pytest.raises(ValueError, match="channel name required"):
        await channel_logout_rpc_payload({}, manager)
    with pytest.raises(KeyError, match="Channel not found: missing"):
        await channel_restart_rpc_payload({"channel": "missing"}, manager)
    with pytest.raises(KeyError, match="Channel not found: runtime"):
        await channel_logout_rpc_payload({"channel": "runtime"}, None)


def test_gateway_delegates_channel_rpc_payloads_to_channel_boundary() -> None:
    imports = _imports_from(RPC_CHANNELS)
    top_level_functions = _top_level_functions(RPC_CHANNELS)

    assert ("opensquilla.channels.rpc_payload", "channel_status_rpc_payload") in imports
    assert ("opensquilla.channels.rpc_payload", "channel_logout_rpc_payload") in imports
    assert ("opensquilla.channels.rpc_payload", "channel_restart_rpc_payload") in imports
    assert "_configured_channel_entries" not in top_level_functions
    assert "_health_extra" not in top_level_functions
    assert "_status_for" not in top_level_functions
    assert "_channel_status" not in top_level_functions
