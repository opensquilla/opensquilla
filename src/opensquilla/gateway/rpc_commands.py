"""Slash-command catalog RPC.

Exposes :data:`opensquilla.commands.DEFAULT_REGISTRY` to non-Python
surfaces (initially the web frontend) so the slash-menu list comes from
one source rather than being hardcoded per-surface. Read-only.
"""

from __future__ import annotations

from typing import Any

from opensquilla.commands import commands_for_surface_rpc_payload
from opensquilla.gateway.rpc import RpcContext, get_dispatcher

_d = get_dispatcher()


@_d.method("commands.list_for_surface", scope="operator.read")
async def _handle_commands_list_for_surface(
    params: dict | None, _ctx: RpcContext
) -> dict[str, Any]:
    return commands_for_surface_rpc_payload(params)
