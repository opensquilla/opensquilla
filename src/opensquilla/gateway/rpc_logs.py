"""Logs domain RPC handlers."""

from __future__ import annotations

from typing import Any

from opensquilla.gateway.diagnostics import diagnostics_status_payload
from opensquilla.gateway.rpc import RpcContext, get_dispatcher
from opensquilla.observability.log_rpc import (
    logs_status_rpc_payload,
    logs_tail_rpc_payload,
    logs_trace_rpc_payload,
)

_d = get_dispatcher()


@_d.method("logs.status", scope="operator.read")
async def _handle_logs_status(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    """Report log-related runtime switches without mutating filesystem state."""

    return logs_status_rpc_payload(
        config=getattr(ctx, "config", None),
        diagnostics_state=getattr(ctx, "diagnostics_state", None),
        diagnostics_status=diagnostics_status_payload(
            getattr(ctx, "diagnostics_state", None),
            getattr(ctx, "config", None),
        ),
    )


@_d.method("logs.trace", scope="operator.read")
async def _handle_logs_trace(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    """Return safe trace events for one trace id."""

    return logs_trace_rpc_payload(params)


@_d.method("logs.tail", scope="operator.read")
async def _handle_logs_tail(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    """Tail log file with cursor-based pagination and level filter."""

    return logs_tail_rpc_payload(params)
