"""Channel onboarding RPC handlers."""

from __future__ import annotations

from typing import Any

from opensquilla.gateway.rpc import RpcContext, get_dispatcher
from opensquilla.gateway.rpc_onboarding import (
    _active_config,
    _apply_inplace,
    _persist,
    _require,
)

_d = get_dispatcher()


@_d.method("onboarding.channel.probe", scope="operator.admin")
async def _channel_probe(params: Any, ctx: RpcContext) -> dict[str, Any]:
    from opensquilla.onboarding.mutations import validate_channel_entry
    from opensquilla.onboarding.redaction import redact_channel_entry

    entry = _require(params, "entry")
    if not isinstance(entry, dict):
        raise ValueError("params.entry must be an object")
    normalized = validate_channel_entry(entry)
    type_name = str(normalized.get("type") or "")
    return {
        "status": "ready",
        "connected": False,
        "restartRequired": True,
        "entry": redact_channel_entry(type_name, normalized),
        "warnings": [],
    }


@_d.method("onboarding.channel.upsert", scope="operator.admin")
async def _channel_upsert(params: Any, ctx: RpcContext) -> dict[str, Any]:
    from opensquilla.onboarding.mutations import upsert_channel

    entry = _require(params, "entry")
    if not isinstance(entry, dict):
        raise ValueError("params.entry must be an object")
    cfg = _active_config(ctx)
    res = upsert_channel(cfg, entry_payload=entry)
    _apply_inplace(ctx, res.config)
    config_path = _persist(ctx, res.config, restart_required=True)
    return {
        "changed": res.changed,
        "restartRequired": True,
        "configPath": config_path,
        "entry": res.public_payload,
        "warnings": res.warnings,
    }


@_d.method("onboarding.channel.remove", scope="operator.admin")
async def _channel_remove(params: Any, ctx: RpcContext) -> dict[str, Any]:
    from opensquilla.onboarding.mutations import remove_channel

    name = _require(params, "name")
    cfg = _active_config(ctx)
    res = remove_channel(cfg, name=name)
    _apply_inplace(ctx, res.config)
    config_path = _persist(ctx, res.config, restart_required=True)
    return {
        "changed": res.changed,
        "restartRequired": True,
        "configPath": config_path,
        "removed": name,
    }


async def _toggle(ctx: RpcContext, params: Any, enabled: bool) -> dict[str, Any]:
    from opensquilla.onboarding.mutations import set_channel_enabled

    name = _require(params, "name")
    cfg = _active_config(ctx)
    res = set_channel_enabled(cfg, name=name, enabled=enabled)
    _apply_inplace(ctx, res.config)
    config_path = _persist(ctx, res.config, restart_required=True)
    return {
        "changed": res.changed,
        "restartRequired": True,
        "configPath": config_path,
        "name": name,
        "enabled": enabled,
    }


@_d.method("onboarding.channel.enable", scope="operator.admin")
async def _channel_enable(params: Any, ctx: RpcContext) -> dict[str, Any]:
    return await _toggle(ctx, params, True)


@_d.method("onboarding.channel.disable", scope="operator.admin")
async def _channel_disable(params: Any, ctx: RpcContext) -> dict[str, Any]:
    return await _toggle(ctx, params, False)
