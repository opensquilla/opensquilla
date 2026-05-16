"""RPC payload builders for channel management surfaces."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


async def channel_status_rpc_payload(
    config: Any | None,
    channel_manager: Any | None,
) -> dict[str, Any]:
    """Build the RPC wire payload for configured and managed channels."""

    health_map = await channel_manager.health() if channel_manager else {}
    manager_types = getattr(channel_manager, "_channel_types", {}) if channel_manager else {}
    channels: list[dict[str, Any]] = []
    seen: set[str] = set()

    for entry in _configured_channel_entries(config):
        name = str(entry.get("name") or "")
        if not name:
            continue
        enabled = bool(entry.get("enabled", True))
        health = health_map.get(name)
        extra = _health_extra(health)
        connected = bool(getattr(health, "connected", False)) if health else False
        channels.append(
            _channel_status_row(
                name=name,
                connected=connected,
                enabled=enabled,
                dispatch_state=extra.get("dispatch_state"),
                bot_user_id=getattr(health, "bot_user_id", None) if health else None,
                connected_since=extra.get("connected_since"),
                restart_attempts=extra.get("restart_attempts", 0),
                channel_type=entry.get("type"),
                configured=True,
            )
        )
        seen.add(name)

    for name, health in health_map.items():
        if name in seen:
            continue
        extra = _health_extra(health)
        adapter = channel_manager.get(name) if channel_manager else None
        connected = bool(getattr(health, "connected", False))
        channels.append(
            _channel_status_row(
                name=name,
                connected=connected,
                enabled=True,
                dispatch_state=extra.get("dispatch_state"),
                bot_user_id=getattr(health, "bot_user_id", None),
                connected_since=extra.get("connected_since"),
                restart_attempts=extra.get("restart_attempts", 0),
                channel_type=manager_types.get(name) or type(adapter).__name__,
                configured=False,
            )
        )

    return {"channels": channels}


async def channel_logout_rpc_payload(
    params: Mapping[str, Any] | None,
    channel_manager: Any | None,
) -> dict[str, Any]:
    """Stop a channel and build the RPC wire payload."""

    channel_name = _channel_name_param(params)
    manager = _require_channel(channel_manager, channel_name)
    await manager.stop_channel(channel_name)
    return {"status": "disconnected", "channel": channel_name}


async def channel_restart_rpc_payload(
    params: Mapping[str, Any] | None,
    channel_manager: Any | None,
) -> dict[str, Any]:
    """Restart a channel and build the RPC wire payload."""

    channel_name = _channel_name_param(params)
    manager = _require_channel(channel_manager, channel_name)
    await manager.restart_channel(channel_name)
    return {"status": "restarted", "channel": channel_name}


def _configured_channel_entries(config: Any | None) -> list[dict[str, Any]]:
    channels_cfg = getattr(config, "channels", None)
    entries = getattr(channels_cfg, "channels", None) or []
    out: list[dict[str, Any]] = []
    for entry in entries:
        if hasattr(entry, "model_dump"):
            out.append(entry.model_dump(mode="python"))
        elif isinstance(entry, dict):
            out.append(dict(entry))
    return out


def _channel_name_param(params: Mapping[str, Any] | None) -> str:
    channel_name = None
    if isinstance(params, Mapping):
        channel_name = params.get("channel") or params.get("name")
    if not channel_name:
        raise ValueError("channel name required")
    return str(channel_name)


def _require_channel(channel_manager: Any | None, channel_name: str) -> Any:
    if channel_manager is None or channel_manager.get(channel_name) is None:
        raise KeyError(f"Channel not found: {channel_name}")
    return channel_manager


def _health_extra(health: Any) -> dict[str, Any]:
    extra = getattr(health, "extra", None)
    return extra if isinstance(extra, dict) else {}


def _status_for(*, connected: bool, enabled: bool, dispatch_state: str | None) -> str:
    if not enabled:
        return "disabled"
    if dispatch_state in {"dead", "exhausted", "restarting"}:
        return dispatch_state
    return "connected" if connected else "stopped"


def _channel_status_row(
    *,
    name: str,
    connected: bool,
    enabled: bool,
    dispatch_state: str | None,
    bot_user_id: str | None,
    connected_since: Any,
    restart_attempts: Any,
    channel_type: Any,
    configured: bool,
) -> dict[str, Any]:
    return {
        "name": name,
        "connected": connected,
        "status": _status_for(
            connected=connected,
            enabled=enabled,
            dispatch_state=dispatch_state,
        ),
        "bot_user_id": bot_user_id,
        "connected_since": connected_since,
        "restart_attempts": restart_attempts,
        "type": channel_type,
        "enabled": enabled,
        "configured": configured,
    }
