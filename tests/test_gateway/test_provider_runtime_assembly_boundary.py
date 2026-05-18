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
        "_refresh_openrouter_catalog_and_pricing",
    } <= assembly_functions
    assert "ProviderRuntimeServices" in assembly_classes
    assert {
        ("opensquilla.gateway.provider_runtime_sync", "sync_image_generation"),
        ("opensquilla.provider.model_catalog", "ModelCatalog"),
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
