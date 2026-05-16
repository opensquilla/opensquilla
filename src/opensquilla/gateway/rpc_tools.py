"""RPC handlers for the tools domain."""

from __future__ import annotations

from typing import Any

from opensquilla.gateway.rpc import RpcContext, get_dispatcher
from opensquilla.provider.runtime_status import build_provider_status_payload
from opensquilla.search.execution import (
    search_provider_payload,
    search_query_rpc_payload,
    search_runtime_status,
)
from opensquilla.tools.policy import (
    ToolSurfaceCapabilities,
    tool_surface_capabilities_from_runtime,
)
from opensquilla.tools.registry import get_default_registry

_d = get_dispatcher()


def _tool_surface_capabilities(ctx: RpcContext) -> ToolSurfaceCapabilities:
    return tool_surface_capabilities_from_runtime(
        session_manager=getattr(ctx, "session_manager", None),
        task_runtime=getattr(ctx, "task_runtime", None),
        scheduler=getattr(ctx, "cron_scheduler", None),
        gateway_config=getattr(ctx, "config", None),
        channel_manager=getattr(ctx, "channel_manager", None),
        originating_envelope=getattr(ctx, "originating_envelope", None),
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
    return search_provider_payload()


@_d.method("providers.status", scope="operator.read")
async def _handle_providers_status(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    from opensquilla.onboarding.provider_specs import list_provider_setup_specs

    if params is not None and not isinstance(params, dict):
        raise ValueError("params must be an object")
    provider_filter = (params or {}).get("provider")
    probe_models = bool((params or {}).get("probeModels", False))

    return await build_provider_status_payload(
        list_provider_setup_specs(),
        provider_selector=getattr(ctx, "provider_selector", None),
        config=getattr(ctx, "config", None),
        provider_filter=str(provider_filter) if provider_filter else None,
        probe_models=probe_models,
    )


@_d.method("search.status", scope="operator.read")
async def _handle_search_status(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    if params is not None and not isinstance(params, dict):
        raise ValueError("params must be an object")
    provider = (params or {}).get("provider")
    return search_runtime_status(str(provider) if provider else None)


@_d.method("search.query", scope="operator.write")
async def _handle_search_query(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    return await search_query_rpc_payload(params)
