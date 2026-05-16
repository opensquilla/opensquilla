"""Provider model listing helpers for adapter surfaces."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast


@dataclass(frozen=True, slots=True)
class ProviderModelRow:
    id: str
    name: str
    provider: str
    context_window: int
    capabilities: tuple[str, ...]
    input_cost_per_1k: float
    output_cost_per_1k: float


async def list_provider_model_rows(
    provider_selector: Any | None,
    *,
    provider_filter: str | None = None,
    capabilities_filter: list[str] | None = None,
) -> list[ProviderModelRow]:
    if provider_selector is None:
        return []

    try:
        raw = await provider_selector.list_models()
    except Exception:
        return []

    rows = [_model_info_to_row(_model_info_payload(model)) for model in raw or []]
    if provider_filter:
        rows = [row for row in rows if row.provider == provider_filter]

    if capabilities_filter:
        required = set(capabilities_filter)
        rows = [row for row in rows if required.issubset(set(row.capabilities))]

    return rows


def _models_list_rpc_params(params: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if params is None:
        return {}
    if not isinstance(params, Mapping):
        raise ValueError("params must be an object")
    return params


async def list_provider_models_rpc_payload(
    provider_selector: Any | None,
    params: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Build the RPC wire payload for a provider model listing request."""

    raw = _models_list_rpc_params(params)
    rows = await list_provider_model_rows(
        provider_selector,
        provider_filter=cast(str | None, raw.get("provider")),
        capabilities_filter=cast(list[str] | None, raw.get("capabilities")),
    )
    return [_model_row_to_wire(row) for row in rows]


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


def _model_info_payload(model: Any) -> dict[str, Any]:
    if isinstance(model, dict):
        return model
    model_dump = getattr(model, "model_dump", None)
    if callable(model_dump):
        return cast(dict[str, Any], model_dump())
    return {}


def _model_info_to_row(model: dict[str, Any]) -> ProviderModelRow:
    model_id = str(model.get("model_id") or "")
    display_name = str(model.get("display_name") or model_id)
    return ProviderModelRow(
        id=model_id,
        name=display_name,
        provider=str(model.get("provider") or ""),
        context_window=int(model.get("context_window") or 0),
        capabilities=_model_capabilities(model),
        input_cost_per_1k=float(model.get("input_cost_per_1k") or 0.0),
        output_cost_per_1k=float(model.get("output_cost_per_1k") or 0.0),
    )


def _model_capabilities(model: dict[str, Any]) -> tuple[str, ...]:
    capabilities = ["chat"]
    if model.get("supports_tools"):
        capabilities.append("tools")
    return tuple(capabilities)
