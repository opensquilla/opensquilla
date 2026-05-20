"""RPC handlers for the tools domain."""

from __future__ import annotations

import os
from typing import Any

from opensquilla.gateway.rpc import RpcContext, get_dispatcher
from opensquilla.tools.builtin.web import (
    get_active_provider,
    run_web_search_payload,
    search_runtime_status,
)
from opensquilla.tools.registry import get_default_registry
from opensquilla.tools.rpc_payload import (
    tools_catalog_payload,
    tools_effective_payload,
)

_d = get_dispatcher()


@_d.method("tools.catalog", scope="operator.read")
async def _handle_tools_catalog(params: dict | None, ctx: RpcContext) -> dict:
    tool_registry = getattr(ctx, "tool_registry", None) or get_default_registry()
    return await tools_catalog_payload(
        params,
        tool_registry=tool_registry,
        session_manager=getattr(ctx, "session_manager", None),
        task_runtime=getattr(ctx, "task_runtime", None),
        scheduler=getattr(ctx, "cron_scheduler", None),
        gateway_config=getattr(ctx, "config", None),
        channel_manager=getattr(ctx, "channel_manager", None),
        originating_envelope=getattr(ctx, "originating_envelope", None),
        is_owner=ctx.principal.is_owner,
    )


@_d.method("tools.effective", scope="operator.read")
async def _handle_tools_effective(params: dict | None, ctx: RpcContext) -> dict:
    tool_registry = getattr(ctx, "tool_registry", None) or get_default_registry()
    return await tools_effective_payload(
        params,
        tool_registry=tool_registry,
        session_manager=getattr(ctx, "session_manager", None),
        task_runtime=getattr(ctx, "task_runtime", None),
        scheduler=getattr(ctx, "cron_scheduler", None),
        gateway_config=getattr(ctx, "config", None),
        channel_manager=getattr(ctx, "channel_manager", None),
        originating_envelope=getattr(ctx, "originating_envelope", None),
        is_owner=ctx.principal.is_owner,
    )


@_d.method("tools.search_provider", scope="operator.read")
async def _handle_tools_search_provider(params: dict | None, ctx: RpcContext) -> dict:
    return {"provider": get_active_provider()}


def _active_llm_provider(ctx: RpcContext) -> str | None:
    selector = getattr(ctx, "provider_selector", None)
    current_config = getattr(selector, "current_config", None)
    provider = getattr(current_config, "provider", None)
    if provider:
        return str(provider)
    llm_cfg = getattr(getattr(ctx, "config", None), "llm", None)
    provider = getattr(llm_cfg, "provider", None)
    return str(provider) if provider else None


def _provider_key_configured(provider_id: str, env_key: str, ctx: RpcContext) -> bool:
    active = provider_id == _active_llm_provider(ctx)
    llm_cfg = getattr(getattr(ctx, "config", None), "llm", None)
    if active and bool(getattr(llm_cfg, "api_key", "")):
        return True
    return bool(env_key and os.environ.get(env_key))


def _provider_base_url(provider_id: str, default_base_url: str, ctx: RpcContext) -> str:
    active = provider_id == _active_llm_provider(ctx)
    llm_cfg = getattr(getattr(ctx, "config", None), "llm", None)
    configured_base_url = getattr(llm_cfg, "base_url", None)
    if active and configured_base_url:
        return str(configured_base_url)
    return default_base_url


async def _model_probe(provider_id: str, ctx: RpcContext) -> dict[str, Any]:
    selector = getattr(ctx, "provider_selector", None)
    if selector is None:
        return {
            "attempted": True,
            "status": "unavailable",
            "count": 0,
            "error": "No provider selector configured",
        }
    try:
        rows = await selector.list_models()
        matching = [
            row
            for row in rows
            if isinstance(row, dict) and str(row.get("provider") or "") == provider_id
        ]
        return {"attempted": True, "status": "ok", "count": len(matching), "error": None}
    except Exception as exc:  # noqa: BLE001 - diagnostic surface
        return {"attempted": True, "status": "error", "count": 0, "error": str(exc)}


@_d.method("providers.status", scope="operator.read")
async def _handle_providers_status(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    from opensquilla.onboarding.provider_specs import list_provider_setup_specs
    from opensquilla.provider.selector import ProviderBuildError, build_provider

    if params is not None and not isinstance(params, dict):
        raise ValueError("params must be an object")
    provider_filter = (params or {}).get("provider")
    probe_models = bool((params or {}).get("probeModels", False))

    specs = list_provider_setup_specs()
    by_id = {spec.provider_id: spec for spec in specs}
    if provider_filter:
        provider_filter = str(provider_filter)
        if provider_filter not in by_id:
            raise ValueError(f"Unknown provider: {provider_filter}")
        specs = [by_id[provider_filter]]

    active = _active_llm_provider(ctx)
    llm_cfg = getattr(getattr(ctx, "config", None), "llm", None)
    rows: list[dict[str, Any]] = []
    for spec in specs:
        is_active = spec.provider_id == active
        api_key_configured = _provider_key_configured(spec.provider_id, spec.env_key, ctx)
        base_url = _provider_base_url(spec.provider_id, spec.default_base_url, ctx)
        base_url_configured = bool(base_url)
        configured = (
            spec.runtime_supported
            and (not spec.requires_api_key or api_key_configured)
            and (not spec.requires_base_url or base_url_configured)
        )
        model = str(getattr(llm_cfg, "model", "") or "") if is_active else ""
        error: str | None = None
        buildable = False
        try:
            build_provider(
                spec.provider_id,
                model or "diagnostic-model",
                api_key=str(getattr(llm_cfg, "api_key", "") or "") if is_active else "",
                base_url=base_url,
            )
            buildable = True
        except ProviderBuildError as exc:
            error = str(exc)
        except Exception as exc:  # noqa: BLE001 - diagnostic surface
            error = str(exc)
        probe = (
            await _model_probe(spec.provider_id, ctx)
            if probe_models and is_active
            else {"attempted": False, "status": "skipped", "count": 0, "error": None}
        )
        rows.append(
            {
                "providerId": spec.provider_id,
                "active": is_active,
                "configured": configured,
                "buildable": buildable,
                "model": model,
                "requiresApiKey": spec.requires_api_key,
                "apiKeyConfigured": api_key_configured,
                "baseUrlConfigured": base_url_configured,
                "error": error,
                "modelProbe": probe,
            }
        )
    return {"activeProvider": active, "providers": rows, "count": len(rows)}


@_d.method("search.status", scope="operator.read")
async def _handle_search_status(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    if params is not None and not isinstance(params, dict):
        raise ValueError("params must be an object")
    provider = (params or {}).get("provider")
    return search_runtime_status(str(provider) if provider else None)


def _query_limit(params: dict[str, Any]) -> int | None:
    if "limit" not in params or params.get("limit") is None:
        return None
    try:
        limit = int(params["limit"])
    except (TypeError, ValueError) as exc:
        raise ValueError("params.limit must be an integer") from exc
    if limit < 1 or limit > 20:
        raise ValueError("params.limit must be between 1 and 20")
    return limit


@_d.method("search.query", scope="operator.write")
async def _handle_search_query(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    if not isinstance(params, dict):
        raise ValueError("params must be an object")
    query = str(params.get("query") or "").strip()
    if not query:
        raise ValueError("params.query is required")
    provider = params.get("provider")
    provider_name = str(provider) if provider else None
    if provider_name:
        search_runtime_status(provider_name)
    payload = await run_web_search_payload(
        query,
        _query_limit(params),
        provider_name=provider_name,
    )
    error = payload.get("error")
    if payload.get("ok", False):
        result = {
            "ok": True,
            "query": payload.get("query", query),
            "provider": payload.get("provider", provider_name or get_active_provider()),
            "results": payload.get("results", []),
        }
        if payload.get("fallbackFrom"):
            result["fallbackFrom"] = payload.get("fallbackFrom")
        if payload.get("attempts") is not None:
            result["attempts"] = payload.get("attempts")
        return result
    if not isinstance(error, dict):
        error = {
            "kind": payload.get("error_kind", "unknown"),
            "class": payload.get("error_class", ""),
            "message": str(payload.get("error") or ""),
            "retryable": False,
        }
    result = {
        "ok": False,
        "query": payload.get("query", query),
        "provider": payload.get("provider", provider_name or get_active_provider()),
        "results": payload.get("results", []),
        "error": error,
    }
    if payload.get("attempts") is not None:
        result["attempts"] = payload.get("attempts")
    return result
