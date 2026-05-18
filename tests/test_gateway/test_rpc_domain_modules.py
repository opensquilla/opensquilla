from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GATEWAY = ROOT / "src/opensquilla/gateway"
RPC_INIT = GATEWAY / "rpc/__init__.py"
RPC_TOOLS = GATEWAY / "rpc_tools.py"
RPC_PROVIDERS = GATEWAY / "rpc_providers.py"
RPC_SEARCH = GATEWAY / "rpc_search.py"


def _imports_from(path: Path) -> set[tuple[str, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                imports.add((node.module, alias.name))
    return imports


def _method_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            func = decorator.func
            if not (
                isinstance(func, ast.Attribute)
                and func.attr == "method"
                and decorator.args
                and isinstance(decorator.args[0], ast.Constant)
                and isinstance(decorator.args[0].value, str)
            ):
                continue
            names.add(decorator.args[0].value)
    return names


def test_gateway_rpc_domain_modules_are_registered() -> None:
    source = RPC_INIT.read_text(encoding="utf-8")

    assert "import opensquilla.gateway.rpc_providers" in source
    assert "import opensquilla.gateway.rpc_search" in source


def test_provider_and_search_rpc_methods_live_outside_tools_module() -> None:
    assert RPC_PROVIDERS.is_file()
    assert RPC_SEARCH.is_file()

    tools_methods = _method_names(RPC_TOOLS)
    provider_methods = _method_names(RPC_PROVIDERS)
    search_methods = _method_names(RPC_SEARCH)

    assert tools_methods == {"tools.catalog", "tools.effective"}
    assert provider_methods == {"providers.status"}
    assert search_methods == {"tools.search_provider", "search.status", "search.query"}

    tools_imports = _imports_from(RPC_TOOLS)
    assert not any(module == "opensquilla.provider.runtime_status" for module, _ in tools_imports)
    assert not any(module == "opensquilla.search.execution" for module, _ in tools_imports)
