from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

from opensquilla.gateway.config import GatewayConfig
from opensquilla.gateway.llm_runtime import resolve_llm_runtime_config
from opensquilla.gateway.provider_runtime_sync import (
    build_provider_selector_from_runtime as gateway_build_provider_selector_from_runtime,
)
from opensquilla.gateway.provider_runtime_sync import (
    provider_config_from_runtime,
)
from opensquilla.gateway.rpc_onboarding import _sync_provider_selector
from opensquilla.provider.selector_materialization import (
    build_provider_selector_from_runtime,
)
from opensquilla.provider.selector_materialization import (
    provider_config_from_runtime as provider_provider_config_from_runtime,
)

ROOT = Path(__file__).resolve().parents[2]
GATEWAY = ROOT / "src/opensquilla/gateway"
BOOT = GATEWAY / "boot.py"
RPC_ONBOARDING = GATEWAY / "rpc_onboarding.py"
PROVIDER_RUNTIME_SYNC = GATEWAY / "provider_runtime_sync.py"
PROVIDER_BOOTSTRAP = GATEWAY / "provider_bootstrap.py"
PROVIDER_RUNTIME_ASSEMBLY = GATEWAY / "provider_runtime_assembly.py"


class _CapturingSelector:
    def __init__(self) -> None:
        self.synced = None

    def sync_primary(self, cfg) -> None:
        self.synced = cfg


def _imports_from(path: Path) -> set[tuple[str, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        (node.module or "", alias.name)
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }


def _function_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def test_provider_runtime_sync_owns_gateway_selector_materialization() -> None:
    boot_imports = _imports_from(BOOT)
    onboarding_imports = _imports_from(RPC_ONBOARDING)
    boundary_imports = _imports_from(PROVIDER_RUNTIME_SYNC)
    assert PROVIDER_BOOTSTRAP.exists()
    bootstrap_imports = _imports_from(PROVIDER_BOOTSTRAP)
    assembly_imports = _imports_from(PROVIDER_RUNTIME_ASSEMBLY)

    provider_config_symbols = {
        ("opensquilla.provider.selector", "ProviderConfig"),
        ("opensquilla.provider.selector", "SelectorConfig"),
    }
    provider_selector_symbols = {
        ("opensquilla.provider.selector", "ModelSelector"),
        *provider_config_symbols,
    }

    assert provider_config_symbols.isdisjoint(boot_imports)
    assert provider_selector_symbols.isdisjoint(onboarding_imports)
    assert ("opensquilla.gateway.llm_runtime", "resolve_llm_runtime_config") not in (
        onboarding_imports
    )
    assert (
        "opensquilla.gateway.provider_bootstrap",
        "build_provider_runtime_services",
    ) in boot_imports
    assert (
        "opensquilla.gateway.provider_runtime_sync",
        "sync_provider_selector",
    ) in onboarding_imports
    assert provider_selector_symbols.isdisjoint(boundary_imports)
    assert (
        "opensquilla.provider.selector_materialization",
        "build_provider_selector_from_runtime",
    ) in boundary_imports
    assert (
        "opensquilla.gateway.provider_runtime_assembly",
        "build_provider_runtime_services",
    ) in bootstrap_imports
    assert (
        "opensquilla.provider.selector_materialization",
        "build_provider_selector_from_runtime",
    ) in assembly_imports
    assert "build_provider_selector_from_runtime" not in _function_names(
        PROVIDER_RUNTIME_SYNC
    )


def test_build_provider_selector_from_runtime_preserves_effective_fields() -> None:
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

    selector = build_provider_selector_from_runtime(
        runtime,
        base_url="https://normalized.example/api",
    )
    current = selector.current_config

    assert current.provider == "openrouter"
    assert current.model == "openai/gpt-5-mini"
    assert current.api_key == "config-key"
    assert current.base_url == "https://normalized.example/api"
    assert current.proxy == "http://127.0.0.1:7890"
    assert current.provider_routing["custom/model"] == "custom-provider"
    assert current.provider_routing["deepseek/deepseek-v4-flash"] == "deepseek"


def test_gateway_sync_keeps_selector_materialization_compatibility_imports() -> None:
    assert gateway_build_provider_selector_from_runtime is build_provider_selector_from_runtime
    assert provider_config_from_runtime is provider_provider_config_from_runtime


def test_rpc_onboarding_provider_sync_uses_effective_runtime_config(
    monkeypatch,
) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://deepseek.example")
    cfg = GatewayConfig(llm={"provider": "deepseek", "api_key": "", "base_url": ""})
    selector = _CapturingSelector()
    ctx = SimpleNamespace(config=cfg, provider_selector=selector)

    _sync_provider_selector(ctx, cfg)

    assert selector.synced.provider == "deepseek"
    assert selector.synced.api_key == "deepseek-key"
    assert selector.synced.base_url == "https://deepseek.example"
