from __future__ import annotations

import ast
from pathlib import Path

from opensquilla.search import runtime as search_runtime
from opensquilla.tools.builtin import web

ROOT = Path(__file__).resolve().parents[2]
WEB_TOOL = ROOT / "src/opensquilla/tools/builtin/web.py"
BOOT = ROOT / "src/opensquilla/gateway/boot.py"
RPC_ONBOARDING = ROOT / "src/opensquilla/gateway/rpc_onboarding.py"
RPC_ONBOARDING_SEARCH = ROOT / "src/opensquilla/gateway/rpc_onboarding_search.py"
RPC_TOOLS = ROOT / "src/opensquilla/gateway/rpc_tools.py"
RPC_SEARCH = ROOT / "src/opensquilla/gateway/rpc_search.py"


def _top_level_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
    return names


def _imports_from(path: Path) -> set[tuple[str, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                imports.add((node.module, alias.name))
    return imports


def test_web_tool_does_not_own_search_runtime_state() -> None:
    top_level_names = _top_level_names(WEB_TOOL)

    assert not {
        "_active_provider",
        "_active_max_results",
        "_active_search_proxy",
        "_active_search_api_key",
        "_active_search_use_env_proxy",
        "_active_search_fallback_policy",
        "_active_search_diagnostics",
    } & top_level_names


def test_web_tool_does_not_own_search_execution() -> None:
    top_level_names = _top_level_names(WEB_TOOL)

    assert not {
        "_classify_search_error",
        "_format_search_error",
        "_search_error_payload",
        "_search_payload",
        "_search_success_payload",
    } & top_level_names
    assert ("opensquilla.search.execution", "run_search_payload") in _imports_from(WEB_TOOL)


def test_gateway_configures_search_runtime_boundary() -> None:
    forbidden = ("opensquilla.tools.builtin.web", "configure_search")

    assert forbidden not in _imports_from(BOOT)
    assert forbidden not in _imports_from(RPC_ONBOARDING)
    assert forbidden not in _imports_from(RPC_ONBOARDING_SEARCH)
    assert ("opensquilla.search.runtime", "configure_search") in _imports_from(BOOT)
    assert ("opensquilla.search.runtime", "configure_search") not in _imports_from(
        RPC_ONBOARDING
    )
    assert ("opensquilla.search.runtime", "configure_search") in _imports_from(
        RPC_ONBOARDING_SEARCH
    )


def test_gateway_reads_search_provider_from_runtime_boundary() -> None:
    assert ("opensquilla.tools.builtin.web", "get_active_provider") not in _imports_from(RPC_TOOLS)
    assert ("opensquilla.search.runtime", "get_active_provider") not in _imports_from(RPC_TOOLS)
    assert ("opensquilla.search.execution", "search_provider_payload") not in _imports_from(
        RPC_TOOLS
    )
    assert ("opensquilla.search.execution", "search_provider_payload") in _imports_from(
        RPC_SEARCH
    )


def test_gateway_runs_search_queries_through_search_boundary() -> None:
    forbidden = ("opensquilla.tools.builtin.web", "run_web_search_payload")

    assert forbidden not in _imports_from(RPC_TOOLS)
    assert ("opensquilla.search.execution", "run_search_payload") not in _imports_from(RPC_TOOLS)
    assert ("opensquilla.search.execution", "search_query_rpc_payload") not in _imports_from(
        RPC_TOOLS
    )
    assert ("opensquilla.search.execution", "search_query_rpc_payload") in _imports_from(
        RPC_SEARCH
    )
    assert ("opensquilla.search.execution", "search_runtime_status") not in _imports_from(
        RPC_TOOLS
    )
    assert ("opensquilla.search.execution", "search_status_rpc_payload") not in _imports_from(
        RPC_TOOLS
    )
    assert ("opensquilla.search.execution", "search_status_rpc_payload") in _imports_from(
        RPC_SEARCH
    )


def test_web_compat_wrappers_delegate_to_search_runtime() -> None:
    web.configure_search(
        "brave",
        max_results=7,
        api_key="brave-test-key",
        proxy="http://proxy.test",
        use_env_proxy=True,
        fallback_policy="network",
        diagnostics=True,
    )

    runtime = search_runtime.current_search_runtime()
    assert runtime.provider_name == "brave"
    assert runtime.max_results == 7
    assert runtime.provider_kwargs("brave")["api_key"] == "brave-test-key"
    assert web.get_active_provider() == "brave"
    assert web._search_provider_kwargs("brave")["proxy"] == "http://proxy.test"

    search_runtime.reset_search_runtime()
    assert web.get_active_provider() == "duckduckgo"
