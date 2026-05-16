from __future__ import annotations

import pytest

from opensquilla.provider import ModelInfo
from opensquilla.provider.model_listing import list_provider_model_rows


class FakeModelSelector:
    def __init__(self, models: list[object]) -> None:
        self.models = models

    async def list_models(self) -> list[object]:
        return self.models


class FailingModelSelector:
    async def list_models(self) -> list[object]:
        raise RuntimeError("provider unavailable")


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
async def test_list_provider_model_rows_returns_empty_when_selector_unavailable() -> None:
    assert await list_provider_model_rows(None) == []
    assert await list_provider_model_rows(FailingModelSelector()) == []
