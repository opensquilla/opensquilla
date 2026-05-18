from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GATEWAY = ROOT / "src/opensquilla/gateway"
RPC_SESSIONS = GATEWAY / "rpc_sessions.py"
RPC_SESSION_READ_QUERIES = GATEWAY / "rpc_session_read_queries.py"


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _imports_from(tree: ast.Module) -> set[tuple[str, str]]:
    return {
        (node.module or "", alias.name)
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }


def _top_level_async_functions(tree: ast.Module) -> dict[str, ast.AsyncFunctionDef]:
    return {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef)
    }


def _top_level_functions(tree: ast.Module) -> dict[str, ast.FunctionDef]:
    return {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
    }


def test_session_read_queries_module_owns_read_query_implementation() -> None:
    assert RPC_SESSION_READ_QUERIES.is_file()

    read_tree = _tree(RPC_SESSION_READ_QUERIES)
    read_async_functions = _top_level_async_functions(read_tree)
    read_functions = _top_level_functions(read_tree)
    read_imports = _imports_from(read_tree)

    assert {
        "list_task_rows",
        "list_task_rows_by_session",
        "resolve_session_node",
        "handle_sessions_list",
        "handle_sessions_subscribe",
        "handle_sessions_unsubscribe",
        "handle_sessions_messages_subscribe",
        "handle_sessions_messages_unsubscribe",
        "handle_sessions_preview",
        "handle_sessions_resolve",
    } <= read_async_functions.keys()
    assert {"require_session_key"} <= read_functions.keys()
    assert {
        ("opensquilla.session.rpc_payload", "messages_subscribe_response"),
        ("opensquilla.session.rpc_payload", "session_list_response"),
        ("opensquilla.session.rpc_payload", "session_list_row"),
        ("opensquilla.session.rpc_payload", "session_preview_response"),
        ("opensquilla.session.rpc_payload", "session_preview_row"),
        ("opensquilla.session.rpc_payload", "session_resolve_response"),
    } <= read_imports


def test_rpc_sessions_read_query_handlers_delegate_to_boundary() -> None:
    sessions_tree = _tree(RPC_SESSIONS)
    imports = _imports_from(sessions_tree)
    handlers = _top_level_async_functions(sessions_tree)

    assert ("opensquilla.gateway", "rpc_session_read_queries") in imports

    expected = {
        "_handle_sessions_list": "handle_sessions_list",
        "_handle_sessions_subscribe": "handle_sessions_subscribe",
        "_handle_sessions_unsubscribe": "handle_sessions_unsubscribe",
        "_handle_sessions_messages_subscribe": "handle_sessions_messages_subscribe",
        "_handle_sessions_messages_unsubscribe": "handle_sessions_messages_unsubscribe",
        "_handle_sessions_preview": "handle_sessions_preview",
        "_handle_sessions_resolve": "handle_sessions_resolve",
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

    direct_payload_imports = {
        ("opensquilla.session.rpc_payload", "messages_subscribe_response"),
        ("opensquilla.session.rpc_payload", "session_list_response"),
        ("opensquilla.session.rpc_payload", "session_list_row"),
        ("opensquilla.session.rpc_payload", "session_preview_response"),
        ("opensquilla.session.rpc_payload", "session_preview_row"),
        ("opensquilla.session.rpc_payload", "session_resolve_response"),
    }
    assert direct_payload_imports.isdisjoint(imports)
