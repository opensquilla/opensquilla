from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

from opensquilla.gateway.config import GatewayConfig
from opensquilla.search import runtime as search_runtime
from opensquilla.tools.builtin import web

ROOT = Path(__file__).resolve().parents[2]
WEB_TOOL = ROOT / "src/opensquilla/tools/builtin/web.py"
BOOT = ROOT / "src/opensquilla/gateway/boot.py"
EXTENSION_RUNTIME = ROOT / "src/opensquilla/extension_services/gateway_runtime.py"
RPC_ONBOARDING = ROOT / "src/opensquilla/gateway/rpc_onboarding.py"
RPC_ONBOARDING_SEARCH = ROOT / "src/opensquilla/gateway/rpc_onboarding_search.py"
RPC_TOOLS = ROOT / "src/opensquilla/gateway/rpc_tools.py"
RPC_SEARCH = ROOT / "src/opensquilla/gateway/rpc_search.py"
SEARCH_EXECUTION = ROOT / "src/opensquilla/search/execution.py"
SEARCH_RPC_PAYLOAD = ROOT / "src/opensquilla/search/rpc_payload.py"


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
    runtime_forbidden = ("opensquilla.search.runtime", "configure_search")
    runtime_sync = ("opensquilla.search.runtime", "sync_search_runtime_from_config")

    assert forbidden not in _imports_from(BOOT)
    assert forbidden not in _imports_from(RPC_ONBOARDING)
    assert forbidden not in _imports_from(RPC_ONBOARDING_SEARCH)
    assert runtime_forbidden not in _imports_from(BOOT)
    assert runtime_forbidden not in _imports_from(RPC_ONBOARDING)
    assert runtime_forbidden not in _imports_from(RPC_ONBOARDING_SEARCH)
    assert runtime_sync not in _imports_from(BOOT)
    assert runtime_sync in _imports_from(EXTENSION_RUNTIME)
    assert runtime_sync in _imports_from(RPC_ONBOARDING_SEARCH)


def test_gateway_reads_search_provider_from_runtime_boundary() -> None:
    assert ("opensquilla.tools.builtin.web", "get_active_provider") not in _imports_from(RPC_TOOLS)
    assert ("opensquilla.search.runtime", "get_active_provider") not in _imports_from(RPC_TOOLS)
    assert ("opensquilla.search.execution", "search_provider_payload") not in _imports_from(
        RPC_TOOLS
    )
    assert ("opensquilla.search.rpc_payload", "search_provider_payload") in _imports_from(
        RPC_SEARCH
    )


def test_gateway_runs_search_queries_through_search_boundary() -> None:
    forbidden = ("opensquilla.tools.builtin.web", "run_web_search_payload")

    assert forbidden not in _imports_from(RPC_TOOLS)
    assert ("opensquilla.search.execution", "run_search_payload") not in _imports_from(RPC_TOOLS)
    assert ("opensquilla.search.execution", "search_query_rpc_payload") not in _imports_from(
        RPC_TOOLS
    )
    assert ("opensquilla.search.execution", "search_runtime_status") not in _imports_from(
        RPC_TOOLS
    )
    assert ("opensquilla.search.execution", "search_status_rpc_payload") not in _imports_from(
        RPC_TOOLS
    )
    assert ("opensquilla.search.rpc_payload", "search_provider_payload") in _imports_from(
        RPC_SEARCH
    )
    assert ("opensquilla.search.rpc_payload", "search_query_rpc_payload") in _imports_from(
        RPC_SEARCH
    )
    assert ("opensquilla.search.rpc_payload", "search_status_rpc_payload") in _imports_from(
        RPC_SEARCH
    )


def test_search_rpc_payload_boundary_owns_request_and_wire_shape() -> None:
    assert SEARCH_RPC_PAYLOAD.exists()

    execution_names = _top_level_names(SEARCH_EXECUTION)
    rpc_payload_names = _top_level_names(SEARCH_RPC_PAYLOAD)

    rpc_owned_names = {
        "search_provider_payload",
        "search_status_rpc_payload",
        "search_query_rpc_payload",
    }
    assert rpc_owned_names <= rpc_payload_names
    assert not {
        "_search_status_rpc_params",
        "_query_limit_from_params",
        "_search_rpc_payload",
    } & execution_names
    # Public imports from search.execution remain as thin compatibility wrappers.
    assert rpc_owned_names <= execution_names
    source = SEARCH_EXECUTION.read_text(encoding="utf-8")
    assert source.count("Compatibility wrapper for the search") == 3


def test_search_runtime_sync_from_config_preserves_bootstrap_policy(monkeypatch) -> None:
    monkeypatch.setenv("CUSTOM_BRAVE_KEY", "env-brave-key")
    config = GatewayConfig(
        search_provider="duckduckgo",
        search_api_key_env="CUSTOM_BRAVE_KEY",
        search_max_results=9,
        search_proxy="http://proxy.test",
        search_use_env_proxy=True,
        search_fallback_policy="network",
        search_diagnostics=True,
    )

    runtime = search_runtime.sync_search_runtime_from_config(config)

    assert runtime.provider_name == "brave"
    assert runtime.max_results == 9
    assert runtime.api_key == "env-brave-key"
    assert runtime.proxy == "http://proxy.test"
    assert runtime.use_env_proxy is True
    assert runtime.fallback_policy == "network"
    assert runtime.diagnostics is True
    assert search_runtime.search_provider_kwargs("brave") == {
        "api_key": "env-brave-key",
        "proxy": "http://proxy.test",
        "use_env_proxy": True,
        "diagnostics": True,
    }


def test_search_runtime_sync_from_config_preserves_explicit_provider(monkeypatch) -> None:
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "env-brave-key")
    config = SimpleNamespace(
        search_provider="brave",
        search_api_key="explicit-brave-key",
        search_api_key_env="",
        search_max_results=3,
        search_proxy="",
        search_use_env_proxy=False,
        search_fallback_policy="not-valid",
        search_diagnostics=False,
    )

    runtime = search_runtime.sync_search_runtime_from_config(config)

    assert runtime.provider_name == "brave"
    assert runtime.max_results == 3
    assert runtime.api_key == "explicit-brave-key"
    assert runtime.fallback_policy == "off"


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
