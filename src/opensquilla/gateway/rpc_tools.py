"""RPC handlers for the tools domain."""

from __future__ import annotations

from opensquilla.gateway.rpc import RpcContext, get_dispatcher
from opensquilla.tools.rpc_payload import (
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
