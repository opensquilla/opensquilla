"""Channels domain RPC handlers."""

from __future__ import annotations

from typing import Any

from opensquilla.channels.rpc_payload import (
    channel_logout_rpc_payload,
    channel_restart_rpc_payload,
    channel_status_rpc_payload,
)
from opensquilla.gateway.rpc import RpcContext, get_dispatcher

_d = get_dispatcher()


@_d.method("channels.status", scope="operator.read")
async def _handle_channels_status(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    return await channel_status_rpc_payload(getattr(ctx, "config", None), ctx.channel_manager)


@_d.method("channels.logout", scope="operator.admin")
async def _handle_channels_logout(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    return await channel_logout_rpc_payload(params, ctx.channel_manager)


@_d.method("channels.restart", scope="operator.admin")
async def _handle_channels_restart(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    return await channel_restart_rpc_payload(params, ctx.channel_manager)
