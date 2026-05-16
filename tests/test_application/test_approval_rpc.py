from __future__ import annotations

from pathlib import Path

import pytest

from opensquilla.application.approval_queue import ApprovalQueue
from opensquilla.application.approval_rpc import (
    approval_forget_rpc_payload,
    approval_request_rpc_payload,
    approval_resolve_rpc_payload,
    approval_settings_rpc_payload,
    approval_snapshot_rpc_payload,
    approval_wait_decision_rpc_payload,
)
from opensquilla.application.intent_cache import IntentApprovalCache


def test_approval_settings_rpc_payload_includes_node_inheritance() -> None:
    queue = ApprovalQueue(db_path=":memory:")
    try:
        settings = queue.set_settings(
            "prompt",
            allow_patterns=["uv *"],
            deny_patterns=["rm *"],
            node_id="node-1",
        )

        assert approval_settings_rpc_payload(
            settings,
            node_id="node-1",
            inherited=False,
        ) == {
            "mode": "prompt",
            "allowPatterns": ["uv *"],
            "denyPatterns": ["rm *"],
            "nodeId": "node-1",
            "inherited": False,
        }
    finally:
        queue.close()


def test_approval_request_rpc_payload_applies_settings_mode() -> None:
    queue = ApprovalQueue(db_path=":memory:")
    try:
        queue.set_settings("auto-approve")

        payload = approval_request_rpc_payload(
            queue,
            namespace="exec",
            params={"toolName": "exec_command", "args": {}, "sessionKey": "agent:main:demo"},
        )

        assert payload["mode"] == "auto-approve"
        assert payload["approved"] is True
        assert payload["resolved"] is True
        assert payload["pending"] is False
        assert queue.status(payload["id"])["params"]["approvalMode"] == "auto-approve"
    finally:
        queue.close()


@pytest.mark.asyncio
async def test_wait_and_resolve_rpc_payloads_preserve_status_shape() -> None:
    queue = ApprovalQueue(db_path=":memory:", poll_interval=0.01)
    try:
        request = approval_request_rpc_payload(
            queue,
            namespace="plugin",
            params={"pluginId": "demo", "version": "1.0.0", "permissions": []},
        )
        approval_id = request["id"]

        resolved = approval_resolve_rpc_payload(queue, approval_id, True)
        waited = await approval_wait_decision_rpc_payload(queue, approval_id)

        assert resolved == waited
        assert waited == {
            "id": approval_id,
            "mode": "prompt",
            "approved": True,
            "resolved": True,
            "consumed": False,
            "pending": False,
        }
    finally:
        queue.close()


def test_approval_snapshot_and_forget_payloads_own_wire_shapes() -> None:
    queue = ApprovalQueue(db_path=":memory:")
    intent_cache = IntentApprovalCache()
    try:
        queue.set_settings("prompt")
        intent_cache.record_always("rm /tmp/approval-demo")
        normalized_target = str(Path("/tmp/approval-demo").resolve(strict=False))

        snapshot = approval_snapshot_rpc_payload(queue, intent_cache)
        assert snapshot == {
            "mode": "prompt",
            "intent_cache_size": 1,
            "intent_cache_entries": [
                {
                    "kind": "delete",
                    "target": normalized_target,
                    "scope": "always",
                }
            ],
        }

        assert approval_forget_rpc_payload(intent_cache, " /tmp/approval-demo ") == {
            "scope": "target",
            "target": "/tmp/approval-demo",
        }
        assert intent_cache.check("rm /tmp/approval-demo") is False

        intent_cache.record_always("rm /tmp/approval-demo")
        assert approval_forget_rpc_payload(intent_cache) == {"scope": "all"}
        assert intent_cache.check("rm /tmp/approval-demo") is False
    finally:
        queue.close()
