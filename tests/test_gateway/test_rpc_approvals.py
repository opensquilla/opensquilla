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

    top_level_functions = {
        node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    assert "_settings_payload" not in top_level_functions
    assert "_status_payload" not in top_level_functions
    assert "_request_approval" not in top_level_functions
