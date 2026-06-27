"""Channels domain RPC handlers."""

from __future__ import annotations

from typing import Any

from opensquilla.channels.contract import (
    channel_capability_profile,
    channel_platform_manifest,
)
from opensquilla.gateway.rpc import RpcContext, get_dispatcher

_d = get_dispatcher()


def _channel_status(connected: bool) -> str:
    return "connected" if connected else "stopped"


def _configured_channel_entries(ctx: RpcContext) -> list[dict[str, Any]]:
    config = getattr(ctx, "config", None)
    channels_cfg = getattr(config, "channels", None)
    entries = getattr(channels_cfg, "channels", None) or []
    out: list[dict[str, Any]] = []
    for entry in entries:
        if hasattr(entry, "model_dump"):
            out.append(entry.model_dump(mode="python"))
        elif isinstance(entry, dict):
            out.append(dict(entry))
    return out


def _health_extra(health: Any) -> dict[str, Any]:
    extra = getattr(health, "extra", None)
    return extra if isinstance(extra, dict) else {}


def _status_for(*, connected: bool, enabled: bool, dispatch_state: str | None) -> str:
    if not enabled:
        return "disabled"
    if dispatch_state in {"dead", "exhausted", "restarting"}:
        return dispatch_state
    return _channel_status(connected)


def _capability_payload(adapter: Any | None) -> tuple[list[str], dict[str, Any] | None]:
    profile = channel_capability_profile(adapter)
    if profile is None:
        return [], None
    return sorted(profile.capability_tags()), {
        "channel_type": profile.channel_type,
        "transports": list(profile.transports),
    }


def _platform_manifest_payload(adapter: Any | None) -> dict[str, Any] | None:
    manifest = channel_platform_manifest(adapter)
    return manifest.to_dict() if manifest is not None else None


def _manager_start_errors(manager: Any | None) -> dict[str, Any]:
    if manager is None:
        return {}
    start_errors = getattr(manager, "start_errors", None)
    if not callable(start_errors):
        return {}
    try:
        errors = start_errors()
    except Exception:
        return {}
    return errors if isinstance(errors, dict) else {}


def _diagnostic_from_start_error(start_error: Any) -> dict[str, Any] | None:
    if not isinstance(start_error, dict):
        return None
    diagnostic = start_error.get("diagnostic")
    if isinstance(diagnostic, dict):
        out = dict(diagnostic)
        out.setdefault("source", "start_error")
        return out
    error_type = str(start_error.get("error_type") or "StartupError")
    return {
        "error_class": "startup_failed",
        "message": f"Channel failed during startup: {error_type}",
        "retryable": False,
        "source": "start_error",
    }


def _diagnostic_from_health_extra(extra: dict[str, Any]) -> dict[str, Any] | None:
    diagnostic = extra.get("last_error")
    if not isinstance(diagnostic, dict):
        return None
    out = dict(diagnostic)
    out.setdefault("source", "adapter")
    return out


def _diagnostics_payload(
    *,
    extra: dict[str, Any] | None = None,
    start_error: Any = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"network_probe": "not_run"}
    last_error = _diagnostic_from_start_error(start_error)
    if last_error is None and extra is not None:
        last_error = _diagnostic_from_health_extra(extra)
    if last_error is not None:
        payload["last_error"] = last_error
    return payload


@_d.method("channels.status", scope="operator.read")
async def _handle_channels_status(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    health_map = await ctx.channel_manager.health() if ctx.channel_manager else {}
    start_errors = _manager_start_errors(ctx.channel_manager)
    manager_types = (
        getattr(ctx.channel_manager, "_channel_types", {}) if ctx.channel_manager else {}
    )
    channels: list[dict[str, Any]] = []
    seen: set[str] = set()

    for entry in _configured_channel_entries(ctx):
        name = str(entry.get("name") or "")
        if not name:
            continue
        enabled = bool(entry.get("enabled", True))
        health = health_map.get(name)
        extra = _health_extra(health)
        adapter = ctx.channel_manager.get(name) if ctx.channel_manager else None
        capabilities, capability_profile = _capability_payload(adapter)
        platform_manifest = _platform_manifest_payload(adapter)
        connected = bool(getattr(health, "connected", False)) if health else False
        channels.append(
            {
                "name": name,
                "connected": connected,
                "status": _status_for(
                    connected=connected,
                    enabled=enabled,
                    dispatch_state=extra.get("dispatch_state"),
                ),
                "bot_user_id": getattr(health, "bot_user_id", None) if health else None,
                "connected_since": extra.get("connected_since"),
                "restart_attempts": extra.get("restart_attempts", 0),
                "type": entry.get("type"),
                "enabled": enabled,
                "configured": True,
                "capabilities": capabilities,
                "capability_profile": capability_profile,
                "platform_manifest": platform_manifest,
                "diagnostics": _diagnostics_payload(
                    extra=extra,
                    start_error=start_errors.get(name),
                ),
            }
        )
        seen.add(name)

    for name, health in health_map.items():
        if name in seen:
            continue
        extra = _health_extra(health)
        adapter = ctx.channel_manager.get(name) if ctx.channel_manager else None
        capabilities, capability_profile = _capability_payload(adapter)
        platform_manifest = _platform_manifest_payload(adapter)
        connected = bool(getattr(health, "connected", False))
        channels.append(
            {
                "name": name,
                "connected": connected,
                "status": _status_for(
                    connected=connected,
                    enabled=True,
                    dispatch_state=extra.get("dispatch_state"),
                ),
                "bot_user_id": getattr(health, "bot_user_id", None),
                "connected_since": extra.get("connected_since"),
                "restart_attempts": extra.get("restart_attempts", 0),
                "type": manager_types.get(name) or type(adapter).__name__,
                "enabled": True,
                "configured": False,
                "capabilities": capabilities,
                "capability_profile": capability_profile,
                "platform_manifest": platform_manifest,
                "diagnostics": _diagnostics_payload(
                    extra=extra,
                    start_error=start_errors.get(name),
                ),
            }
        )

    return {"channels": channels}


@_d.method("channels.logout", scope="operator.admin")
async def _handle_channels_logout(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    channel_name = None
    if isinstance(params, dict):
        channel_name = params.get("channel") or params.get("name")
    if not channel_name:
        raise ValueError("channel name required")
    if ctx.channel_manager is None:
        raise KeyError(f"Channel not found: {channel_name}")
    if ctx.channel_manager.get(channel_name) is None:
        raise KeyError(f"Channel not found: {channel_name}")
    await ctx.channel_manager.stop_channel(channel_name)
    return {"status": "disconnected", "channel": channel_name}


@_d.method("channels.restart", scope="operator.admin")
async def _handle_channels_restart(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    channel_name = None
    if isinstance(params, dict):
        channel_name = params.get("channel") or params.get("name")
    if not channel_name:
        raise ValueError("channel name required")
    if ctx.channel_manager is None:
        raise KeyError(f"Channel not found: {channel_name}")
    if ctx.channel_manager.get(channel_name) is None:
        raise KeyError(f"Channel not found: {channel_name}")
    await ctx.channel_manager.restart_channel(channel_name)
    return {"status": "restarted", "channel": channel_name}
