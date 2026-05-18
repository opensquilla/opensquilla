"""RPC handlers for the providers domain."""

from __future__ import annotations

from typing import Any

from opensquilla.gateway.rpc import RpcContext, get_dispatcher
from opensquilla.provider.runtime_status import build_provider_status_rpc_payload

_d = get_dispatcher()


@_d.method("providers.status", scope="operator.read")
async def _handle_providers_status(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    from opensquilla.onboarding.provider_specs import list_provider_setup_specs

    return await build_provider_status_rpc_payload(
        list_provider_setup_specs(),
        params,
        provider_selector=getattr(ctx, "provider_selector", None),
        config=getattr(ctx, "config", None),
    )
