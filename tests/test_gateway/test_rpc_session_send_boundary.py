from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GATEWAY = ROOT / "src/opensquilla/gateway"
RPC_SESSIONS = GATEWAY / "rpc_sessions.py"
RPC_SESSION_SEND = GATEWAY / "rpc_session_send.py"


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


def test_session_send_module_owns_send_orchestration() -> None:
    assert RPC_SESSION_SEND.is_file()

    send_tree = _tree(RPC_SESSION_SEND)
    send_functions = _top_level_functions(send_tree)
    send_async_functions = _top_level_async_functions(send_tree)
    send_imports = _imports_from(send_tree)

    assert "optional_positive_timeout" in send_functions
    assert "handle_sessions_send" in send_async_functions
    assert {
        ("opensquilla.gateway", "attachment_ingest"),
        ("opensquilla.gateway.agent_tasks", "get_agent_task_registry"),
        ("opensquilla.gateway.rpc", "RpcContext"),
        ("opensquilla.gateway.rpc_session_turn_runtime", "enqueue_session_turn_via_runtime"),
        ("opensquilla.session.services", "get_session_lock"),
        ("opensquilla.session.services", "get_session_storage"),
        ("opensquilla.paths", "media_root_from_config"),
        ("opensquilla.session.keys", "normalize_agent_id"),
        ("opensquilla.session.rpc_payload", "normalize_terminal_event_payload"),
        ("opensquilla.session.rpc_payload", "session_send_accepted_response"),
    } <= send_imports


def test_rpc_sessions_send_handler_delegates_to_boundary() -> None:
    sessions_tree = _tree(RPC_SESSIONS)
    imports = _imports_from(sessions_tree)
    handlers = _top_level_async_functions(sessions_tree)

    assert ("opensquilla.gateway", "rpc_session_send") in imports

    handler = handlers["_handle_sessions_send"]
    calls = [
        node
        for node in ast.walk(handler)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "handle_sessions_send"
    ]
    returns = [node for node in ast.walk(handler) if isinstance(node, ast.Return)]

    assert len(calls) == 1
    assert len(returns) == 1

    direct_send_imports = {
        ("opensquilla.gateway.agent_tasks", "get_agent_task_registry"),
        ("opensquilla.gateway.rpc_session_turn_runtime", "enqueue_session_turn_via_runtime"),
        ("opensquilla.paths", "media_root_from_config"),
        ("opensquilla.session.rpc_payload", "normalize_terminal_event_payload"),
        ("opensquilla.session.rpc_payload", "session_send_accepted_response"),
    }
    assert direct_send_imports.isdisjoint(imports)
