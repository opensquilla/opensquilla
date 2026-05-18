"""RPC adapters for Gateway session create/patch management."""

from __future__ import annotations

from opensquilla.gateway.rpc import RpcContext
from opensquilla.session.management_service import create_session, patch_session


async def handle_sessions_create(params: dict | None, ctx: RpcContext) -> dict:
    return await create_session(params, ctx)


async def handle_sessions_patch(params: dict | None, ctx: RpcContext) -> dict:
    return await patch_session(params, ctx)
