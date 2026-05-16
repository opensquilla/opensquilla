from __future__ import annotations

import ast
from pathlib import Path

import pytest

from opensquilla.application.approval_queue import ApprovalQueue
from opensquilla.gateway import rpc_approvals
from opensquilla.gateway.rpc import RpcContext, get_dispatcher


@pytest.mark.asyncio
async def test_exec_approval_rpc_delegates_payload_to_application_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = ApprovalQueue(db_path=":memory:")
    monkeypatch.setattr(rpc_approvals, "get_approval_queue", lambda: queue)
    try:
        queue.set_settings("auto-deny")

        result = await get_dispatcher().dispatch(
            "r1",
            "exec.approval.request",
            {"toolName": "exec_command", "args": {}, "sessionKey": "agent:main:demo"},
            RpcContext(conn_id="test"),
        )

        assert result.error is None, result.error
        assert result.payload["mode"] == "auto-deny"
        assert result.payload["approved"] is False
        assert result.payload["resolved"] is True
        assert result.payload["pending"] is False
    finally:
        queue.close()


def test_gateway_rpc_approvals_keeps_payload_logic_out_of_gateway_boundary() -> None:
    source = Path(rpc_approvals.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    ]

    top_level_functions = {
        node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    helper_names = {
        "approval_forget_rpc_payload",
        "approval_snapshot_rpc_payload",
    }
    imported_helpers = {
        alias.name
        for node in imports
        if node.module == "opensquilla.application.approval_rpc"
        for alias in node.names
    }
    handlers = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name in {"_handle_exec_approval_snapshot", "_handle_exec_approval_forget"}
    }
    handler_names = {
        node.id
        for handler in handlers.values()
        for node in ast.walk(handler)
        if isinstance(node, ast.Name)
    }
    direct_key_sets = {
        tuple(key.value for key in node.keys if isinstance(key, ast.Constant))
        for handler in handlers.values()
        for node in ast.walk(handler)
        if isinstance(node, ast.Dict)
    }
    private_attrs = {
        node.attr
        for handler in handlers.values()
        for node in ast.walk(handler)
        if isinstance(node, ast.Attribute)
    }

    assert "_settings_payload" not in top_level_functions
    assert "_status_payload" not in top_level_functions
    assert "_request_approval" not in top_level_functions
    assert helper_names.issubset(imported_helpers)
    assert helper_names.issubset(handler_names)
    assert ("mode", "intent_cache_size", "intent_cache_entries") not in direct_key_sets
    assert ("kind", "target", "scope") not in direct_key_sets
    assert ("scope", "target") not in direct_key_sets
    assert ("scope",) not in direct_key_sets
    assert "_entries" not in private_attrs
