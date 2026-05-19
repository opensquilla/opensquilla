from __future__ import annotations

import pytest

from opensquilla.provider import ModelInfo, model_listing
from opensquilla.provider.model_listing import (
    ProviderModelCatalog,
    list_provider_model_rows,
    list_provider_models_rpc_payload,
    load_provider_model_catalog,
)


class FakeModelSelector:
    def __init__(self, models: list[object]) -> None:
        self.models = models

    async def list_models(self) -> list[object]:
        return self.models


class FailingModelSelector:
    async def list_models(self) -> list[object]:
        raise RuntimeError("provider unavailable")


@pytest.mark.asyncio
async def test_provider_model_catalog_snapshot_normalizes_filters_and_counts() -> None:
    selector = FakeModelSelector(
        [
            {"provider": "openrouter", "model_id": "a", "supports_tools": True},
            ModelInfo(
                provider="openrouter",
                model_id="b",
                context_window=200,
                supports_tools=False,
            ),
            {"provider": "ollama", "model_id": "c", "supports_tools": True},
        ]
    )

    catalog = await load_provider_model_catalog(selector)

    assert isinstance(catalog, ProviderModelCatalog)
    assert catalog.count_provider("openrouter") == 2
    assert catalog.count_provider("ollama") == 1
    assert [
        row.id
        for row in catalog.filter(
            model_listing.ProviderModelQuery(
                provider="openrouter",
                capabilities=("tools",),
            )
        )
    ] == ["a"]
    assert [row.id for row in catalog.rows] == ["a", "b", "c"]


@pytest.mark.asyncio
async def test_list_provider_model_rows_normalizes_dict_and_model_info() -> None:
    selector = FakeModelSelector(
        [
            {
                "provider": "openrouter",
                "model_id": "openrouter/a",
                "display_name": "A",
                "context_window": 123,
                "supports_tools": True,
                "input_cost_per_1k": 0.1,
                "output_cost_per_1k": 0.2,
            },
            ModelInfo(
                provider="ollama",
                model_id="local/b",
                context_window=456,
                supports_tools=False,
            ),
        ]
    )

    rows = await list_provider_model_rows(selector)

    assert rows[0].id == "openrouter/a"
    assert rows[0].name == "A"
    assert rows[0].provider == "openrouter"
    assert rows[0].context_window == 123
    assert rows[0].capabilities == ("chat", "tools")
    assert rows[0].input_cost_per_1k == 0.1
    assert rows[0].output_cost_per_1k == 0.2
    assert rows[1].id == "local/b"
    assert rows[1].name == "local/b"
    assert rows[1].capabilities == ("chat",)


@pytest.mark.asyncio
async def test_list_provider_model_rows_filters_provider_and_capabilities() -> None:
    selector = FakeModelSelector(
        [
            {"provider": "openrouter", "model_id": "a", "supports_tools": True},
            {"provider": "openrouter", "model_id": "b", "supports_tools": False},
            {"provider": "ollama", "model_id": "c", "supports_tools": True},
        ]
    )

    rows = await list_provider_model_rows(
        selector,
        provider_filter="openrouter",
        capabilities_filter=["tools"],
    )

    assert [row.id for row in rows] == ["a"]


@pytest.mark.asyncio
async def test_provider_model_query_owns_provider_and_capability_filters() -> None:
    selector = FakeModelSelector(
        [
            {"provider": "openrouter", "model_id": "a", "supports_tools": True},
            {"provider": "openrouter", "model_id": "b", "supports_tools": False},
            {"provider": "ollama", "model_id": "c", "supports_tools": True},
        ]
    )

    assert hasattr(model_listing, "ProviderModelQuery")
    query = model_listing.ProviderModelQuery(
        provider="openrouter",
        capabilities=("tools",),
    )

    rows = await list_provider_model_rows(selector, query=query)

    assert [row.id for row in rows] == ["a"]


@pytest.mark.asyncio
async def test_list_provider_models_rpc_payload_preserves_wire_shape_and_filters() -> None:
    selector = FakeModelSelector(
        [
            {
                "provider": "openrouter",
                "model_id": "a",
                "display_name": "A",
                "context_window": 123,
                "supports_tools": True,
                "input_cost_per_1k": 0.1,
                "output_cost_per_1k": 0.2,
            },
            {"provider": "ollama", "model_id": "b", "supports_tools": True},
        ]
    )

    payload = await list_provider_models_rpc_payload(
        selector,
        {"provider": "openrouter", "capabilities": ["tools"]},
    )

    assert payload == [
        {
            "id": "a",
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


@pytest.mark.asyncio
async def test_list_provider_models_rpc_payload_validates_request_shape() -> None:
    with pytest.raises(ValueError, match="params must be an object"):
        await list_provider_models_rpc_payload(
            FakeModelSelector([]),
            "bad-params",  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_list_provider_model_rows_returns_empty_when_selector_unavailable() -> None:
    assert await list_provider_model_rows(None) == []
    assert await list_provider_model_rows(FailingModelSelector()) == []
