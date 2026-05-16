"""Usage domain RPC handlers — wired to session manager."""

from __future__ import annotations

import time
from typing import Any

from opensquilla.gateway.rpc import RpcContext, get_dispatcher
from opensquilla.session.usage_rpc import (
    usage_cost_rpc_payload,
    usage_status_rpc_payload,
)

_d = get_dispatcher()


def _now_ms() -> int:
    return int(time.time() * 1000)


@_d.method("usage.status", scope="operator.read")
async def _handle_usage_status(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    return await usage_status_rpc_payload(
        session_manager=getattr(ctx, "session_manager", None),
        usage_tracker=getattr(ctx, "usage_tracker", None),
        config=getattr(ctx, "config", None),
        now_ms=_now_ms(),
    )


@_d.method("usage.cost", scope="operator.read")
async def _handle_usage_cost(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    return await usage_cost_rpc_payload(
        session_manager=getattr(ctx, "session_manager", None),
        usage_tracker=getattr(ctx, "usage_tracker", None),
        config=getattr(ctx, "config", None),
        now_ms=_now_ms(),
    )
