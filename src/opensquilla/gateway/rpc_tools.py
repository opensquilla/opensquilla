"""RPC handlers for the tools domain."""

from __future__ import annotations

from typing import Any

from opensquilla.gateway.rpc import RpcContext, get_dispatcher
from opensquilla.provider.image_generation_runtime import image_generation_available
from opensquilla.provider.runtime_status import (
    ProviderModelProbe,
    ProviderStatusRow,
    build_provider_status_report,
)
from opensquilla.search.execution import run_search_payload, search_runtime_status
from opensquilla.search.runtime import get_active_provider
from opensquilla.tools.policy import ToolSurfaceCapabilities
from opensquilla.tools.registry import get_default_registry

_d = get_dispatcher()


def _tool_surface_capabilities(ctx: RpcContext) -> ToolSurfaceCapabilities:
    try:
        image_generation = image_generation_available()
    except Exception:
        image_generation = False
    return ToolSurfaceCapabilities(
        session_manager=getattr(ctx, "session_manager", None) is not None,
        task_runtime=getattr(ctx, "task_runtime", None) is not None,
        scheduler=getattr(ctx, "cron_scheduler", None) is not None,
        gateway_config=getattr(ctx, "config", None) is not None,
        channel_backing=(
            getattr(ctx, "channel_manager", None) is not None
            or getattr(ctx, "originating_envelope", None) is not None
        ),
        image_generation=image_generation,
    )


@_d.method("tools.catalog", scope="operator.read")
async def _handle_tools_catalog(params: dict | None, ctx: RpcContext) -> dict:
    raw = params or {}
    profile = raw.get("profile")
    tool_registry = getattr(ctx, "tool_registry", None) or get_default_registry()
    tools = await tool_registry.list_tools(
        profile=profile,
        session_key=raw.get("sessionKey"),
        agent_id=raw.get("agentId"),
        caller_kind=raw.get("callerKind"),
        interaction_mode=raw.get("interactionMode"),
        tool_surface_capabilities=_tool_surface_capabilities(ctx),
        is_owner=ctx.principal.is_owner,
    )
    return {"tools": tools}


@_d.method("tools.effective", scope="operator.read")
async def _handle_tools_effective(params: dict | None, ctx: RpcContext) -> dict:
    raw = params or {}
    session_key = raw.get("sessionKey")
    agent_id = raw.get("agentId")
    caller_kind = raw.get("callerKind")
    interaction_mode = raw.get("interactionMode")
    tool_registry = getattr(ctx, "tool_registry", None) or get_default_registry()
    tools = await tool_registry.effective_tools(
        session_key=session_key,
        agent_id=agent_id,
        caller_kind=caller_kind,
        interaction_mode=interaction_mode,
        tool_surface_capabilities=_tool_surface_capabilities(ctx),
        is_owner=ctx.principal.is_owner,
    )
    return {"tools": tools}


@_d.method("tools.search_provider", scope="operator.read")
async def _handle_tools_search_provider(params: dict | None, ctx: RpcContext) -> dict:
    return {"provider": get_active_provider()}


def _model_probe_to_wire(probe: ProviderModelProbe) -> dict[str, Any]:
    return {
        "attempted": probe.attempted,
        "status": probe.status,
        "count": probe.count,
        "error": probe.error,
    }


def _provider_status_row_to_wire(row: ProviderStatusRow) -> dict[str, Any]:
    return {
        "providerId": row.provider_id,
        "active": row.active,
        "configured": row.configured,
        "buildable": row.buildable,
        "model": row.model,
        "requiresApiKey": row.requires_api_key,
        "apiKeyConfigured": row.api_key_configured,
        "baseUrlConfigured": row.base_url_configured,
        "error": row.error,
        "modelProbe": _model_probe_to_wire(row.model_probe),
    }


@_d.method("providers.status", scope="operator.read")
async def _handle_providers_status(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    from opensquilla.onboarding.provider_specs import list_provider_setup_specs

    if params is not None and not isinstance(params, dict):
        raise ValueError("params must be an object")
    provider_filter = (params or {}).get("provider")
    probe_models = bool((params or {}).get("probeModels", False))

    report = await build_provider_status_report(
        list_provider_setup_specs(),
        provider_selector=getattr(ctx, "provider_selector", None),
        config=getattr(ctx, "config", None),
        provider_filter=str(provider_filter) if provider_filter else None,
        probe_models=probe_models,
    )
    rows = [_provider_status_row_to_wire(row) for row in report.rows]
    return {"activeProvider": report.active_provider, "providers": rows, "count": len(rows)}


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
    payload = await run_search_payload(
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
