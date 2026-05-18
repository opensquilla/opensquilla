from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GATEWAY = ROOT / "src/opensquilla/gateway"
RPC_SESSIONS = GATEWAY / "rpc_sessions.py"
RPC_SESSION_LIFECYCLE = GATEWAY / "rpc_session_lifecycle.py"


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


def test_session_lifecycle_module_owns_lifecycle_implementation() -> None:
    assert RPC_SESSION_LIFECYCLE.is_file()

    lifecycle_tree = _tree(RPC_SESSION_LIFECYCLE)
    lifecycle_functions = _top_level_async_functions(lifecycle_tree)
    lifecycle_imports = _imports_from(lifecycle_tree)

    assert {
        "handle_sessions_abort",
        "handle_sessions_reset",
        "handle_sessions_delete",
        "handle_sessions_context_compact",
        "handle_sessions_compact",
        "drain_task_runtime_for_reset",
    } <= lifecycle_functions.keys()
    assert {
        ("opensquilla.session.lifecycle_service", "require_existing_session"),
        ("opensquilla.session.lifecycle_service", "require_session_storage"),
        ("opensquilla.session.lifecycle_service", "run_with_session_lock"),
        ("opensquilla.session.lifecycle_flush", "execute_lifecycle_flush"),
        ("opensquilla.session.lifecycle_flush", "unavailable_flush_failure_for_transcript"),
        ("opensquilla.session.rpc_payload", "session_abort_response"),
        ("opensquilla.session.rpc_payload", "session_reset_response"),
        ("opensquilla.session.rpc_payload", "session_delete_response"),
        ("opensquilla.session.rpc_payload", "session_context_compact_response"),
        ("opensquilla.session.rpc_payload", "session_compact_response"),
    } <= lifecycle_imports

    direct_flush_payload_imports = {
        ("opensquilla.session.rpc_payload", "session_flush_error_details"),
        ("opensquilla.session.rpc_payload", "session_flush_unavailable_details"),
        ("opensquilla.session.rpc_payload", "session_permission_denied_details"),
    }
    assert direct_flush_payload_imports.isdisjoint(lifecycle_imports)


def test_rpc_sessions_lifecycle_handlers_delegate_to_boundary() -> None:
    sessions_tree = _tree(RPC_SESSIONS)
    imports = _imports_from(sessions_tree)
    handlers = _top_level_async_functions(sessions_tree)

    assert ("opensquilla.gateway", "rpc_session_lifecycle") in imports

    expected = {
        "_handle_sessions_abort": "handle_sessions_abort",
        "_handle_sessions_reset": "handle_sessions_reset",
        "_handle_sessions_delete": "handle_sessions_delete",
        "_handle_sessions_context_compact": "handle_sessions_context_compact",
        "_handle_sessions_compact": "handle_sessions_compact",
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
        ("opensquilla.session.rpc_payload", "session_abort_response"),
        ("opensquilla.session.rpc_payload", "session_reset_response"),
        ("opensquilla.session.rpc_payload", "session_delete_response"),
        ("opensquilla.session.rpc_payload", "session_context_compact_response"),
        ("opensquilla.session.rpc_payload", "session_compact_response"),
        ("opensquilla.session.rpc_payload", "session_flush_error_details"),
        ("opensquilla.session.rpc_payload", "session_flush_unavailable_details"),
        ("opensquilla.session.rpc_payload", "session_permission_denied_details"),
    }
    assert direct_payload_imports.isdisjoint(imports)
