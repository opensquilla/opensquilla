"""Search onboarding RPC handlers."""

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


def _sync_search_provider(config: Any) -> None:
    from opensquilla.search.runtime import configure_search

    configure_search(
        provider_name=config.search_provider,
        max_results=config.search_max_results,
        api_key=config.search_api_key,
        proxy=config.search_proxy,
        use_env_proxy=config.search_use_env_proxy,
        fallback_policy=config.search_fallback_policy,
        diagnostics=config.search_diagnostics,
    )


@_d.method("onboarding.search.configure", scope="operator.admin")
async def _search_configure(params: Any, ctx: RpcContext) -> dict[str, Any]:
    from opensquilla.onboarding.mutations import upsert_search_provider

    provider_id = _require(params, "providerId")
    cfg = _active_config(ctx)
    res = upsert_search_provider(
        cfg,
        provider_id=provider_id,
        api_key=params.get("apiKey", "") if isinstance(params, dict) else "",
        api_key_env=params.get("apiKeyEnv", "") if isinstance(params, dict) else "",
        max_results=params.get("maxResults", 5) if isinstance(params, dict) else 5,
        proxy=params.get("proxy", "") if isinstance(params, dict) else "",
        use_env_proxy=(params.get("useEnvProxy", False) if isinstance(params, dict) else False),
        fallback_policy=(
            params.get("fallbackPolicy", "off") if isinstance(params, dict) else "off"
        ),
        diagnostics=params.get("diagnostics", False) if isinstance(params, dict) else False,
    )
    _apply_inplace(ctx, res.config)
    _sync_search_provider(res.config)
    config_path = _persist(ctx, res.config, restart_required=res.restart_required)
    return {
        "changed": res.changed,
        "restartRequired": res.restart_required,
        "configPath": config_path,
        "entry": res.public_payload,
        "warnings": res.warnings,
    }
