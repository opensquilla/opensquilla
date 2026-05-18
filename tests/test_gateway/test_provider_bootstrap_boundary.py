from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GATEWAY = ROOT / "src/opensquilla/gateway"
BOOT = GATEWAY / "boot.py"
PROVIDER_BOOTSTRAP = GATEWAY / "provider_bootstrap.py"
PROVIDER_RUNTIME_ASSEMBLY = GATEWAY / "provider_runtime_assembly.py"


def _imports_from(path: Path) -> set[tuple[str, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        (node.module or "", alias.name)
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }


def _function_imports(path: Path, function_name: str) -> set[tuple[str, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == function_name:
                return {
                    (child.module or "", alias.name)
                    for child in ast.walk(node)
                    if isinstance(child, ast.ImportFrom)
                    for alias in child.names
                }
    raise AssertionError(f"{function_name} not found in {path}")


def test_boot_delegates_provider_runtime_startup_to_provider_bootstrap() -> None:
    assert PROVIDER_BOOTSTRAP.exists()

    build_services_imports = _function_imports(BOOT, "build_services")
    bootstrap_imports = _imports_from(PROVIDER_BOOTSTRAP)
    assembly_imports = _imports_from(PROVIDER_RUNTIME_ASSEMBLY)

    assert (
        "opensquilla.gateway.provider_bootstrap",
        "build_provider_runtime_services",
    ) in build_services_imports
    assert (
        "opensquilla.gateway.provider_runtime_sync",
        "build_provider_selector_from_runtime",
    ) not in build_services_imports
    assert ("opensquilla.provider.model_catalog", "ModelCatalog") not in (
        build_services_imports
    )
    assert (
        "opensquilla.provider.image_generation_runtime",
        "configure_image_generation",
    ) not in build_services_imports

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
        "sync_image_generation",
    ) in assembly_imports
    assert ("opensquilla.provider.model_catalog", "ModelCatalog") in assembly_imports
    assert (
        "opensquilla.provider.selector_materialization",
        "build_provider_selector_from_runtime",
    ) in assembly_imports


@pytest.mark.asyncio
async def test_provider_bootstrap_preserves_selector_and_image_runtime_state() -> None:
    assert PROVIDER_BOOTSTRAP.exists()

    from opensquilla.gateway.config import GatewayConfig
    from opensquilla.gateway.provider_bootstrap import build_provider_runtime_services
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
