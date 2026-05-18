"""Router onboarding RPC handlers."""

from __future__ import annotations

from typing import Any

from opensquilla.gateway.rpc import RpcContext, get_dispatcher
from opensquilla.gateway.rpc_onboarding import (
    _active_config,
    _apply_inplace,
    _persist,
    _sync_provider_selector,
)

_d = get_dispatcher()


@_d.method("onboarding.router.catalog", scope="operator.read")
async def _router_catalog(params: Any, ctx: RpcContext) -> dict[str, Any]:
    from opensquilla.onboarding.router_specs import router_catalog_payload

    return router_catalog_payload()


@_d.method("onboarding.router.configure", scope="operator.admin")
async def _router_configure(params: Any, ctx: RpcContext) -> dict[str, Any]:
    from opensquilla.onboarding.mutations import upsert_router

    cfg = _active_config(ctx)
    mode = params.get("mode", "recommended") if isinstance(params, dict) else "recommended"
    default_tier = params.get("defaultTier") if isinstance(params, dict) else None
    tiers = params.get("tiers") if isinstance(params, dict) else None
    res = upsert_router(cfg, mode=mode, default_tier=default_tier, tiers=tiers)
    _apply_inplace(ctx, res.config)
    _sync_provider_selector(ctx, res.config)
    config_path = _persist(ctx, res.config, restart_required=res.restart_required)
    return {
        "changed": res.changed,
        "restartRequired": res.restart_required,
        "configPath": config_path,
        "entry": res.public_payload,
        "warnings": res.warnings,
    }
