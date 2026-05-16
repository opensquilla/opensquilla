from __future__ import annotations

import pytest

from opensquilla.gateway.rpc import RpcContext, get_dispatcher


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
