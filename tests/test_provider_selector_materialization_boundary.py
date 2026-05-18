from __future__ import annotations

import ast
from pathlib import Path

from opensquilla.gateway.config import GatewayConfig
from opensquilla.provider.runtime_config import resolve_llm_runtime_config
from opensquilla.provider.selector_materialization import (
    build_provider_selector_from_runtime,
    provider_config_from_runtime,
)

ROOT = Path(__file__).resolve().parents[1]
GATEWAY = ROOT / "src/opensquilla/gateway"
PROVIDER = ROOT / "src/opensquilla/provider"
PROVIDER_SELECTOR_MATERIALIZATION = PROVIDER / "selector_materialization.py"
GATEWAY_PROVIDER_RUNTIME_SYNC = GATEWAY / "provider_runtime_sync.py"
GATEWAY_PROVIDER_RUNTIME_ASSEMBLY = GATEWAY / "provider_runtime_assembly.py"


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


def test_provider_layer_owns_selector_materialization() -> None:
    assert PROVIDER_SELECTOR_MATERIALIZATION.is_file()

    provider_imports = _imports_from(PROVIDER_SELECTOR_MATERIALIZATION)
    sync_imports = _imports_from(GATEWAY_PROVIDER_RUNTIME_SYNC)
    assembly_imports = _imports_from(GATEWAY_PROVIDER_RUNTIME_ASSEMBLY)
    sync_functions = _top_level_functions(GATEWAY_PROVIDER_RUNTIME_SYNC)
    provider_functions = _top_level_functions(PROVIDER_SELECTOR_MATERIALIZATION)

    provider_selector_symbols = {
        ("opensquilla.provider.selector", "ModelSelector"),
        ("opensquilla.provider.selector", "ProviderConfig"),
        ("opensquilla.provider.selector", "SelectorConfig"),
    }
    assert provider_selector_symbols <= provider_imports
    assert provider_selector_symbols.isdisjoint(sync_imports)
    assert {
        "provider_config_from_runtime",
        "build_provider_selector_from_runtime",
    } <= provider_functions
    assert "provider_config_from_runtime" not in sync_functions
    assert "build_provider_selector_from_runtime" not in sync_functions
    assert (
        "opensquilla.provider.selector_materialization",
        "build_provider_selector_from_runtime",
    ) in sync_imports
    assert (
        "opensquilla.provider.selector_materialization",
        "build_provider_selector_from_runtime",
    ) in assembly_imports


def test_provider_selector_materialization_preserves_runtime_fields() -> None:
    cfg = GatewayConfig(
        llm={
            "provider": "openrouter",
            "model": "openai/gpt-5-mini",
            "api_key": "config-key",
            "base_url": "https://openrouter.example/api",
            "proxy": "http://127.0.0.1:7890",
            "provider_routing": {"custom/model": "custom-provider"},
        }
    )
    runtime = resolve_llm_runtime_config(cfg)

    provider_cfg = provider_config_from_runtime(
        runtime,
        base_url="https://normalized.example/api",
    )
    selector = build_provider_selector_from_runtime(
        runtime,
        base_url="https://normalized.example/api",
    )
    current = selector.current_config

    assert provider_cfg.provider == current.provider == "openrouter"
    assert provider_cfg.model == current.model == "openai/gpt-5-mini"
    assert provider_cfg.api_key == current.api_key == "config-key"
    assert provider_cfg.base_url == current.base_url == "https://normalized.example/api"
    assert provider_cfg.proxy == current.proxy == "http://127.0.0.1:7890"
    assert provider_cfg.provider_routing["custom/model"] == "custom-provider"
    assert current.provider_routing["deepseek/deepseek-v4-flash"] == "deepseek"
