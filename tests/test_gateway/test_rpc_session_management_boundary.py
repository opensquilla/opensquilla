from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GATEWAY = ROOT / "src/opensquilla/gateway"
RPC_SESSIONS = GATEWAY / "rpc_sessions.py"
RPC_SESSION_MANAGEMENT = GATEWAY / "rpc_session_management.py"


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _imports_from(tree: ast.Module) -> set[tuple[str, str]]:
    return {
        (node.module or "", alias.name)
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }


def _top_level_functions(tree: ast.Module) -> dict[str, ast.FunctionDef]:
    return {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}


def _top_level_async_functions(tree: ast.Module) -> dict[str, ast.AsyncFunctionDef]:
    return {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef)
    }


def test_session_management_module_owns_create_patch_implementation() -> None:
    assert RPC_SESSION_MANAGEMENT.is_file()

    management_tree = _tree(RPC_SESSION_MANAGEMENT)
    management_functions = _top_level_functions(management_tree)
    management_async_functions = _top_level_async_functions(management_tree)
    management_imports = _imports_from(management_tree)

    assert {
        "model_value",
        "agent_registry_model",
        "session_turn_model",
        "create_session_key",
        "require_session_key",
    } <= management_functions.keys()
    assert {
        "agent_registry_has",
        "handle_sessions_create",
        "handle_sessions_patch",
    } <= management_async_functions.keys()
    assert {
        ("opensquilla.gateway.rpc", "RpcContext"),
        ("opensquilla.gateway.rpc", "RpcHandlerError"),
        ("opensquilla.gateway.rpc", "RpcUnavailableError"),
        ("opensquilla.gateway.session_services", "get_session_storage"),
        ("opensquilla.session.keys", "canonicalize_session_key"),
        ("opensquilla.session.keys", "normalize_agent_id"),
        ("opensquilla.session.rpc_payload", "session_agent_not_found_details"),
        ("opensquilla.session.rpc_payload", "session_create_response"),
        ("opensquilla.session.rpc_payload", "session_create_stub_response"),
        ("opensquilla.session.rpc_payload", "session_patch_response"),
    } <= management_imports


def test_rpc_sessions_management_handlers_delegate_to_boundary() -> None:
    sessions_tree = _tree(RPC_SESSIONS)
    imports = _imports_from(sessions_tree)
    functions = _top_level_functions(sessions_tree)
    handlers = _top_level_async_functions(sessions_tree)

    assert ("opensquilla.gateway", "rpc_session_management") in imports

    expected = {
        "_handle_sessions_create": "handle_sessions_create",
        "_handle_sessions_patch": "handle_sessions_patch",
    }
    for handler_name, boundary_name in expected.items():
        handler = handlers[handler_name]
        calls = [
            node
            for node in ast.walk(handler)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == boundary_name
        ]
        returns = [node for node in ast.walk(handler) if isinstance(node, ast.Return)]

        assert len(calls) == 1
        assert len(returns) == 1

    assert "_session_turn_model" in functions
    turn_model_calls = [
        node
        for node in ast.walk(functions["_session_turn_model"])
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "session_turn_model"
    ]
    assert len(turn_model_calls) == 1

    direct_payload_imports = {
        ("opensquilla.session.rpc_payload", "session_agent_not_found_details"),
        ("opensquilla.session.rpc_payload", "session_create_response"),
        ("opensquilla.session.rpc_payload", "session_create_stub_response"),
        ("opensquilla.session.rpc_payload", "session_patch_response"),
    }
    assert direct_payload_imports.isdisjoint(imports)
