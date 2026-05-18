from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GATEWAY = ROOT / "src/opensquilla/gateway"
RPC_PACKAGE = GATEWAY / "rpc/__init__.py"
RPC_ONBOARDING = GATEWAY / "rpc_onboarding.py"
RPC_ONBOARDING_CHANNELS = GATEWAY / "rpc_onboarding_channels.py"
RPC_ONBOARDING_MEMORY = GATEWAY / "rpc_onboarding_memory.py"
RPC_ONBOARDING_ROUTER = GATEWAY / "rpc_onboarding_router.py"
RPC_ONBOARDING_SEARCH = GATEWAY / "rpc_onboarding_search.py"


def _imports_from(path: Path) -> set[tuple[str, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        (node.module or "", alias.name)
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }


def _registered_methods(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    methods: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if (
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and decorator.func.attr == "method"
                and decorator.args
                and isinstance(decorator.args[0], ast.Constant)
                and isinstance(decorator.args[0].value, str)
            ):
                methods.add(decorator.args[0].value)
    return methods


def test_onboarding_domain_rpc_methods_live_in_domain_boundaries() -> None:
    domain_modules = {
        RPC_ONBOARDING_ROUTER: {
            "onboarding.router.catalog",
            "onboarding.router.configure",
        },
        RPC_ONBOARDING_SEARCH: {"onboarding.search.configure"},
        RPC_ONBOARDING_CHANNELS: {
            "onboarding.channel.probe",
            "onboarding.channel.upsert",
            "onboarding.channel.remove",
            "onboarding.channel.enable",
            "onboarding.channel.disable",
        },
        RPC_ONBOARDING_MEMORY: {"onboarding.memory_embedding.configure"},
    }

    core_methods = _registered_methods(RPC_ONBOARDING)
    for module_path, expected_methods in domain_modules.items():
        assert module_path.exists()
        assert expected_methods <= _registered_methods(module_path)
        assert expected_methods.isdisjoint(core_methods)

    assert core_methods == {
        "onboarding.status",
        "onboarding.catalog",
    }


def test_rpc_package_imports_onboarding_domain_boundaries_after_core() -> None:
    tree = ast.parse(RPC_PACKAGE.read_text(encoding="utf-8"), filename=str(RPC_PACKAGE))
    imported_modules = [
        alias.name
        for node in tree.body
        if isinstance(node, ast.Import)
        for alias in node.names
    ]

    core_index = imported_modules.index("opensquilla.gateway.rpc_onboarding")
    for module_name in (
        "opensquilla.gateway.rpc_onboarding_providers",
        "opensquilla.gateway.rpc_onboarding_router",
        "opensquilla.gateway.rpc_onboarding_search",
        "opensquilla.gateway.rpc_onboarding_channels",
        "opensquilla.gateway.rpc_onboarding_memory",
    ):
        assert module_name in imported_modules
        assert core_index < imported_modules.index(module_name)


def test_search_runtime_sync_is_owned_by_search_onboarding_boundary() -> None:
    assert (
        "opensquilla.search.runtime",
        "configure_search",
    ) not in _imports_from(RPC_ONBOARDING)
    assert (
        "opensquilla.search.runtime",
        "configure_search",
    ) in _imports_from(RPC_ONBOARDING_SEARCH)
