"""RPC handlers for the models domain."""

from __future__ import annotations

from typing import Any

from opensquilla.gateway.rpc import RpcContext, get_dispatcher
from opensquilla.provider.model_catalog import ModelCatalog

_d = get_dispatcher()

# Offline layered catalog (corrections + snapshot + synthesized fallback) used
# only to enrich rows with provenance; ``resolve_entry`` never fails and never
# touches the network.
_catalog = ModelCatalog()


def _model_info_to_wire(m: dict[str, Any]) -> dict[str, Any]:
    """Convert a ModelInfo.model_dump() dict to the RPC wire format."""
    capabilities: list[str] = ["chat"]
    if m.get("supports_tools"):
        capabilities.append("tools")
    entry = _catalog.resolve_entry(m.get("model_id", ""), provider=m.get("provider", ""))
    # Providers can signal vision support via extra fields; keep extensible
    return {
        "id": m.get("model_id", ""),
        "name": m.get("display_name") or m.get("model_id", ""),
        "provider": m.get("provider", ""),
        "contextWindow": m.get("context_window", 0),
        "capabilities": capabilities,
        "pricing": {
            "inputPer1k": m.get("input_cost_per_1k", 0.0),
            "outputPer1k": m.get("output_cost_per_1k", 0.0),
        },
        # Catalog provenance; a model unknown to every layer still resolves
        # (source="synthesized") so the key is always present.
        "source": entry.source,
        "reasoningFormat": entry.reasoning_format,
    }


def _list_error_to_wire(err: Any) -> dict[str, Any]:
    """Convert a selector ProviderListError to the RPC wire format."""
    return {
        "provider": str(getattr(err, "provider", "")),
        "kind": str(getattr(err, "kind", "")),
        "detail": str(getattr(err, "detail", "")),
    }


@_d.method("models.list", scope="operator.read")
async def _handle_models_list(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    provider_filter = (params or {}).get("provider")
    capabilities_filter: list[str] | None = (params or {}).get("capabilities")

    models: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    if ctx.provider_selector is not None and getattr(
        ctx.provider_selector, "is_configured", True
    ):
        try:
            detailed = await ctx.provider_selector.list_models_detailed()
            models = [_model_info_to_wire(m) for m in detailed.models]
            errors = [_list_error_to_wire(e) for e in detailed.errors]
        except Exception:
            pass

    if provider_filter:
        models = [m for m in models if m["provider"] == provider_filter]

    if capabilities_filter:
        required = set(capabilities_filter)
        models = [m for m in models if required.issubset(set(m["capabilities"]))]

    return {"models": models, "errors": errors}
