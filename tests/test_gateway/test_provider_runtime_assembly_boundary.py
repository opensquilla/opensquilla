from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GATEWAY = ROOT / "src/opensquilla/gateway"
PROVIDER_BOOTSTRAP = GATEWAY / "provider_bootstrap.py"
PROVIDER_RUNTIME_ASSEMBLY = GATEWAY / "provider_runtime_assembly.py"


def _imports_from(path: Path) -> set[tuple[str, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                imports.add((node.module, alias.name))
    return imports


def _top_level_functions(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _top_level_classes(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {node.name for node in tree.body if isinstance(node, ast.ClassDef)}


def test_provider_bootstrap_delegates_to_runtime_assembly_boundary() -> None:
    assert PROVIDER_RUNTIME_ASSEMBLY.is_file()

    bootstrap_imports = _imports_from(PROVIDER_BOOTSTRAP)
    assembly_imports = _imports_from(PROVIDER_RUNTIME_ASSEMBLY)
    assembly_functions = _top_level_functions(PROVIDER_RUNTIME_ASSEMBLY)
    assembly_classes = _top_level_classes(PROVIDER_RUNTIME_ASSEMBLY)

    assert (
        "opensquilla.gateway.provider_runtime_assembly",
        "build_provider_runtime_services",
    ) in bootstrap_imports
    assert (
        "opensquilla.gateway.provider_runtime_assembly",
        "ProviderRuntimeServices",
    ) in bootstrap_imports
    assert (
        "opensquilla.gateway.provider_runtime_sync",
        "build_provider_selector_from_runtime",
    ) not in bootstrap_imports
    assert (
        "opensquilla.gateway.provider_runtime_sync",
        "sync_image_generation",
    ) not in bootstrap_imports
    assert ("opensquilla.provider.model_catalog", "ModelCatalog") not in bootstrap_imports

    assert {
        "build_provider_runtime_services",
        "normalize_provider_base_url",
    } <= assembly_functions
    assert "_openrouter_pricing_model_ids" not in assembly_functions
    assert "_refresh_openrouter_catalog_and_pricing" not in assembly_functions
    assert "ProviderRuntimeServices" in assembly_classes
    assert {
        ("opensquilla.gateway.provider_runtime_sync", "sync_image_generation"),
        ("opensquilla.provider.model_catalog", "ModelCatalog"),
        ("opensquilla.provider.model_catalog", "openrouter_pricing_model_ids"),
        (
            "opensquilla.provider.model_catalog",
            "refresh_openrouter_catalog_and_pricing",
        ),
        (
            "opensquilla.provider.selector_materialization",
            "build_provider_selector_from_runtime",
        ),
    } <= assembly_imports


@pytest.mark.asyncio
async def test_provider_runtime_assembly_preserves_selector_and_image_runtime_state() -> None:
    assert PROVIDER_RUNTIME_ASSEMBLY.is_file()

    from opensquilla.gateway.config import GatewayConfig
    from opensquilla.gateway.provider_runtime_assembly import (
        build_provider_runtime_services,
    )
    from opensquilla.provider.image_generation_runtime import (
        configure_image_generation,
        current_image_generation_config,
    )

    config = GatewayConfig(
        llm={
            "provider": "deepseek",
            "model": "deepseek-chat",
            "api_key": "llm-key",
            "base_url": "https://deepseek.example/v1",
        }
    )

    configure_image_generation(None)
    try:
        services = await build_provider_runtime_services(config)

        assert services.provider_selector is not None
        assert services.provider_selector.current_config.provider == "deepseek"
        assert services.provider_selector.current_config.model == "deepseek-chat"
        assert services.provider_selector.current_config.api_key == "llm-key"
        assert services.provider_selector.current_config.base_url == (
            "https://deepseek.example"
        )
        assert services.model_catalog is not None
        assert current_image_generation_config() is config.image_generation
    finally:
        configure_image_generation(None)


@pytest.mark.asyncio
async def test_provider_runtime_assembly_delegates_catalog_refresh_to_provider_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.gateway import provider_runtime_assembly
    from opensquilla.gateway.config import GatewayConfig
    from opensquilla.gateway.provider_runtime_assembly import (
        build_provider_runtime_services,
    )

    captured: dict[str, object] = {}

    async def fake_refresh(
        model_catalog,
        *,
        api_key: str,
        base_url: str,
        proxy: str,
        pricing_model_ids,
        refresh_prices,
    ) -> None:
        captured["catalog"] = model_catalog
        captured["api_key"] = api_key
        captured["base_url"] = base_url
        captured["proxy"] = proxy
        captured["pricing_model_ids"] = set(pricing_model_ids)
        captured["refresh_prices"] = refresh_prices

    def fake_refresh_live_prices(models, base_url: str) -> None:
        captured["live_price_models"] = set(models)
        captured["live_price_base_url"] = base_url

    monkeypatch.setattr(
        provider_runtime_assembly,
        "refresh_openrouter_catalog_and_pricing",
        fake_refresh,
    )
    monkeypatch.setattr(
        provider_runtime_assembly,
        "refresh_live_prices",
        fake_refresh_live_prices,
    )

    config = GatewayConfig(
        llm={
            "provider": "openrouter",
            "model": "openrouter/active",
            "api_key": "llm-key",
            "base_url": "https://openrouter.example/api/v1",
        },
        squilla_router={
            "tiers": {
                "fast": {"model": "openrouter/fast"},
                "missing": {},
            }
        },
    )

    services = await build_provider_runtime_services(config, provider_selector=object())

    assert captured["catalog"] is services.model_catalog
    assert captured["api_key"] == "llm-key"
    assert captured["base_url"] == "https://openrouter.example/api"
    assert captured["proxy"] == ""
    assert captured["pricing_model_ids"] == {
        "openrouter/active",
        "openrouter/fast",
    }
    assert captured["refresh_prices"] is fake_refresh_live_prices
