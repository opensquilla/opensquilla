"""RPC handlers for the models domain."""

from __future__ import annotations

from typing import Any

from opensquilla.gateway.rpc import RpcContext, get_dispatcher
from opensquilla.provider.model_listing import ProviderModelRow, list_provider_model_rows

_d = get_dispatcher()


def _model_row_to_wire(row: ProviderModelRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "provider": row.provider,
        "contextWindow": row.context_window,
        "capabilities": list(row.capabilities),
        "pricing": {
            "inputPer1k": row.input_cost_per_1k,
            "outputPer1k": row.output_cost_per_1k,
        },
    }


@_d.method("models.list", scope="operator.read")
async def _handle_models_list(params: dict | None, ctx: RpcContext) -> list[dict[str, Any]]:
    provider_filter = (params or {}).get("provider")
    capabilities_filter: list[str] | None = (params or {}).get("capabilities")

    rows = await list_provider_model_rows(
        ctx.provider_selector,
        provider_filter=provider_filter,
        capabilities_filter=capabilities_filter,
    )
    return [_model_row_to_wire(row) for row in rows]
