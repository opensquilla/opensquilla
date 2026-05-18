"""RPC handlers for the search domain."""

from __future__ import annotations

from typing import Any

from opensquilla.gateway.rpc import RpcContext, get_dispatcher
from opensquilla.search.execution import (
    search_provider_payload,
    search_query_rpc_payload,
    search_status_rpc_payload,
)

_d = get_dispatcher()


@_d.method("tools.search_provider", scope="operator.read")
async def _handle_tools_search_provider(params: dict | None, ctx: RpcContext) -> dict:
    return search_provider_payload()


@_d.method("search.status", scope="operator.read")
async def _handle_search_status(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    return search_status_rpc_payload(params)


@_d.method("search.query", scope="operator.write")
async def _handle_search_query(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    return await search_query_rpc_payload(params)
