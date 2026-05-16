from __future__ import annotations

import ast
from pathlib import Path

import pytest

from opensquilla.gateway.rpc import RpcContext, get_dispatcher

ROOT = Path(__file__).resolve().parents[2]
RPC_MODELS = ROOT / "src/opensquilla/gateway/rpc_models.py"


def _imports_from(path: Path) -> set[tuple[str, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                imports.add((node.module, alias.name))
    return imports


class FakeModelSelector:
    async def list_models(self) -> list[dict[str, object]]:
        return [
            {
                "provider": "openrouter",
                "model_id": "openrouter/a",
                "display_name": "A",
                "context_window": 123,
                "supports_tools": True,
                "input_cost_per_1k": 0.1,
                "output_cost_per_1k": 0.2,
            },
            {
                "provider": "ollama",
                "model_id": "local/b",
                "context_window": 456,
                "supports_tools": False,
            },
        ]


@pytest.mark.asyncio
async def test_models_rpc_list_preserves_wire_shape_and_filters() -> None:
    result = await get_dispatcher().dispatch(
        "r1",
        "models.list",
        {"provider": "openrouter", "capabilities": ["tools"]},
        RpcContext(conn_id="test", provider_selector=FakeModelSelector()),
    )

    assert result.error is None, result.error
    assert result.payload == [
        {
            "id": "openrouter/a",
            "name": "A",
            "provider": "openrouter",
            "contextWindow": 123,
            "capabilities": ["chat", "tools"],
            "pricing": {
                "inputPer1k": 0.1,
                "outputPer1k": 0.2,
            },
        }
    ]


def test_models_rpc_delegates_payload_shape_to_provider_boundary() -> None:
    imports = _imports_from(RPC_MODELS)

    assert (
        "opensquilla.provider.model_listing",
        "list_provider_models_rpc_payload",
    ) in imports
    assert ("opensquilla.provider.model_listing", "ProviderModelRow") not in imports
    assert ("opensquilla.provider.model_listing", "list_provider_model_rows") not in imports
