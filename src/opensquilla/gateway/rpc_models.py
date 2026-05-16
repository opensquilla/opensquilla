"""RPC handlers for the models domain."""

from __future__ import annotations

from typing import Any

from opensquilla.gateway.rpc import RpcContext, get_dispatcher
from opensquilla.provider.model_listing import list_provider_models_rpc_payload

_d = get_dispatcher()


@_d.method("models.list", scope="operator.read")
async def _handle_models_list(params: dict | None, ctx: RpcContext) -> list[dict[str, Any]]:
    return await list_provider_models_rpc_payload(ctx.provider_selector, params)
