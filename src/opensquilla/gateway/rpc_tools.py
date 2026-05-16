"""RPC handlers for the tools domain."""

from __future__ import annotations

from typing import Any

from opensquilla.gateway.rpc import RpcContext, get_dispatcher
from opensquilla.provider.runtime_status import build_provider_status_rpc_payload
from opensquilla.search.execution import (
    search_provider_payload,
    search_query_rpc_payload,
    search_status_rpc_payload,
)
from opensquilla.tools.registry import (
    tools_catalog_payload,
    tools_effective_payload,
)

_d = get_dispatcher()


@_d.method("tools.catalog", scope="operator.read")
async def _handle_tools_catalog(params: dict | None, ctx: RpcContext) -> dict:
    return await tools_catalog_payload(
        params,
        tool_registry=getattr(ctx, "tool_registry", None),
        is_owner=ctx.principal.is_owner,
        session_manager=getattr(ctx, "session_manager", None),
        task_runtime=getattr(ctx, "task_runtime", None),
        scheduler=getattr(ctx, "cron_scheduler", None),
        gateway_config=getattr(ctx, "config", None),
        channel_manager=getattr(ctx, "channel_manager", None),
        originating_envelope=getattr(ctx, "originating_envelope", None),
    )


@_d.method("tools.effective", scope="operator.read")
async def _handle_tools_effective(params: dict | None, ctx: RpcContext) -> dict:
    return await tools_effective_payload(
        params,
        tool_registry=getattr(ctx, "tool_registry", None),
        is_owner=ctx.principal.is_owner,
        session_manager=getattr(ctx, "session_manager", None),
        task_runtime=getattr(ctx, "task_runtime", None),
        scheduler=getattr(ctx, "cron_scheduler", None),
        gateway_config=getattr(ctx, "config", None),
        channel_manager=getattr(ctx, "channel_manager", None),
        originating_envelope=getattr(ctx, "originating_envelope", None),
    )


@_d.method("tools.search_provider", scope="operator.read")
async def _handle_tools_search_provider(params: dict | None, ctx: RpcContext) -> dict:
    return search_provider_payload()


@_d.method("providers.status", scope="operator.read")
async def _handle_providers_status(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    from opensquilla.onboarding.provider_specs import list_provider_setup_specs

    return await build_provider_status_rpc_payload(
        list_provider_setup_specs(),
        params,
        provider_selector=getattr(ctx, "provider_selector", None),
        config=getattr(ctx, "config", None),
    )


@_d.method("search.status", scope="operator.read")
async def _handle_search_status(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    return search_status_rpc_payload(params)


@_d.method("search.query", scope="operator.write")
async def _handle_search_query(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    return await search_query_rpc_payload(params)
