"""Approval queue transitions push WS events to approvals-scoped clients."""

from __future__ import annotations

from typing import Any

import pytest

from opensquilla.application.approval_queue import ApprovalQueue
from opensquilla.gateway.approval_events import (
    build_approval_event_payload,
    register_approval_event_bridge,
)
from opensquilla.gateway.auth import Principal
from opensquilla.gateway.event_bridge import EventBridge


class _FakeConn:
    def __init__(self, conn_id: str, scopes: frozenset[str], role: str = "operator") -> None:
        self.conn_id = conn_id
        self.principal = Principal(
            role=role,
            scopes=scopes,
            is_owner=False,
            authenticated=True,
        )
        self.events: list[tuple[str, dict[str, Any]]] = []

    async def send_event(self, event: str, payload: Any = None) -> None:
        self.events.append((event, payload))


class _FakeRegistry:
    def __init__(self, conns: list[_FakeConn]) -> None:
        self._conns = {conn.conn_id: conn for conn in conns}

    def all(self) -> list[_FakeConn]:
        return list(self._conns.values())

    def get(self, conn_id: str) -> _FakeConn | None:
        return self._conns.get(conn_id)


def _build_bridge(
    conns: list[_FakeConn],
) -> tuple[ApprovalQueue, list[Any], Any]:
    queue = ApprovalQueue(db_path=":memory:")
    bridge = EventBridge(
        subscription_manager=None,
        connection_registry=_FakeRegistry(conns),
    )
    scheduled: list[Any] = []
    remove = register_approval_event_bridge(queue, bridge, schedule=scheduled.append)
    return queue, scheduled, remove


@pytest.mark.asyncio
async def test_exec_approval_request_pushes_event_to_approvals_scoped_client() -> None:
    approvals_conn = _FakeConn("c-approvals", frozenset({"operator.approvals"}))
    read_only_conn = _FakeConn("c-read", frozenset({"operator.read"}))
    node_conn = _FakeConn("c-node", frozenset({"node"}), role="node")
    queue, scheduled, remove = _build_bridge([approvals_conn, read_only_conn, node_conn])
    try:
        approval_id = queue.request(
            namespace="exec",
            params={
                "toolName": "exec_command",
                "command": "rm -rf ./scratch dir",
                "args": {"command": "rm -rf ./scratch dir", "workdir": None},
                "sessionKey": "agent:main:webchat:demo",
                "agent": "main",
            },
        )

        assert len(scheduled) == 1
        await scheduled.pop()

        assert len(approvals_conn.events) == 1
        event_name, payload = approvals_conn.events[0]
        assert event_name == "exec.approval.requested"
        assert payload["approval_id"] == approval_id
        assert payload["namespace"] == "exec"
        assert payload["session_key"] == "agent:main:webchat:demo"
        assert payload["tool_name"] == "exec_command"
        assert payload["command"] == "rm -rf ./scratch dir"
        assert payload["agent"] == "main"
        assert payload["created_at"] > 0
        assert "approved" not in payload
        # The approvals surface stays scoped: read-only and node-role
        # connections must not receive approval pushes.
        assert read_only_conn.events == []
        assert node_conn.events == []
    finally:
        remove()
        queue.close()


@pytest.mark.asyncio
async def test_exec_approval_resolution_mirrors_resolved_event() -> None:
    approvals_conn = _FakeConn("c-approvals", frozenset({"operator.approvals"}))
    queue, scheduled, remove = _build_bridge([approvals_conn])
    try:
        approval_id = queue.request(
            namespace="exec",
            params={
                "toolName": "exec_command",
                "command": "echo hi",
                "sessionKey": "agent:main:webchat:demo",
            },
        )
        await scheduled.pop()

        queue.resolve(approval_id, True)

        assert len(scheduled) == 1
        await scheduled.pop()
        event_name, payload = approvals_conn.events[-1]
        assert event_name == "exec.approval.resolved"
        assert payload["approval_id"] == approval_id
        assert payload["session_key"] == "agent:main:webchat:demo"
        assert payload["approved"] is True

        # Idempotent re-resolution must not emit a second resolved event.
        queue.resolve(approval_id, True)
        assert scheduled == []
    finally:
        remove()
        queue.close()


@pytest.mark.asyncio
async def test_plugin_approval_events_use_plugin_namespace() -> None:
    approvals_conn = _FakeConn("c-approvals", frozenset({"operator.approvals"}))
    queue, scheduled, remove = _build_bridge([approvals_conn])
    try:
        approval_id = queue.request(
            namespace="plugin",
            params={"pluginId": "demo-plugin", "version": "1.0.0", "permissions": []},
        )
        await scheduled.pop()
        queue.resolve(approval_id, False)
        await scheduled.pop()

        assert [name for name, _ in approvals_conn.events] == [
            "plugin.approval.requested",
            "plugin.approval.resolved",
        ]
        requested_payload = approvals_conn.events[0][1]
        assert requested_payload["tool_name"] == "demo-plugin"
        resolved_payload = approvals_conn.events[1][1]
        assert resolved_payload["approved"] is False
    finally:
        remove()
        queue.close()


def test_build_approval_event_payload_falls_back_to_argv_command() -> None:
    payload = build_approval_event_payload(
        {
            "id": "abc123",
            "namespace": "exec",
            "params": {"argv": ["git", "status"], "action_kind": "exec"},
            "created_at": 1.0,
            "resolved": False,
            "approved": False,
        }
    )

    assert payload["command"] == "git status"
    assert payload["tool_name"] == "exec"
    assert payload["session_key"] == ""
