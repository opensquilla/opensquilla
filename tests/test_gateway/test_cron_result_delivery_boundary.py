from __future__ import annotations

import ast
from types import SimpleNamespace
from typing import Any

import pytest

from opensquilla.gateway import boot
from opensquilla.gateway.cron_result_delivery import (
    build_cron_delivery_chain,
    build_cron_result_payload,
    build_sessions_changed_payload,
    make_cron_ws_emitter,
    make_session_forwarder,
)
from opensquilla.gateway.session_streams import SessionStreamRegistry
from opensquilla.scheduler.delivery import DeliveryChain

SESSION_KEY = "agent:main:webchat:origin"
CRON_SESSION_KEY = "cron:drink:run:isolated"


class _FakeConn:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.events: list[tuple[str, dict[str, Any]]] = []

    async def send_event(self, event_name: str, payload: dict[str, Any]) -> None:
        if self.fail:
            raise RuntimeError("send failed")
        self.events.append((event_name, payload))


class _FakeRegistry:
    def __init__(self, conns: dict[str, _FakeConn]) -> None:
        self._conns = conns

    def get(self, conn_id: str) -> _FakeConn | None:
        return self._conns.get(conn_id)


class _FakeSubscriptionManager:
    def __init__(
        self,
        *,
        topic_subscribers: dict[str, set[str]] | None = None,
        message_subscribers: dict[str, set[str]] | None = None,
        session_subscribers: set[str] | None = None,
    ) -> None:
        self._topic_subscribers = topic_subscribers or {}
        self._message_subscribers = message_subscribers or {}
        self._session_subscribers = session_subscribers or set()

    def get_topic_subscribers(self, topic: str) -> set[str]:
        return set(self._topic_subscribers.get(topic, set()))

    def get_message_subscribers(self, session_key: str) -> set[str]:
        return set(self._message_subscribers.get(session_key, set()))

    def get_session_subscribers(self) -> set[str]:
        return set(self._session_subscribers)


class _FakeSessionManager:
    def __init__(self) -> None:
        self.appended: list[dict[str, Any]] = []

    async def append_message(
        self,
        session_key: str,
        role: str,
        content: str,
        provenance: dict[str, Any],
    ) -> Any:
        self.appended.append(
            {
                "session_key": session_key,
                "role": role,
                "content": content,
                "provenance": provenance,
            }
        )
        return SimpleNamespace(
            created_at="2026-05-19T00:00:00+00:00",
            provenance_kind=provenance["kind"],
            provenance_source_tool=provenance["source_tool"],
            provenance_source_session_key=provenance["source_session_key"],
        )


def test_payload_helpers_preserve_cron_result_and_sessions_changed_wire_shape() -> None:
    entry = SimpleNamespace(
        created_at="2026-05-19T00:00:00+00:00",
        provenance_kind="cron",
        provenance_source_tool="cron:drink",
        provenance_source_session_key=CRON_SESSION_KEY,
    )

    assert build_cron_result_payload(SESSION_KEY, "drink logged", entry) == {
        "sessionKey": SESSION_KEY,
        "message": {
            "role": "assistant",
            "text": "drink logged",
            "timestamp": "2026-05-19T00:00:00+00:00",
            "provenanceKind": "cron",
            "provenanceSourceTool": "cron:drink",
            "provenanceSourceSessionKey": CRON_SESSION_KEY,
        },
    }
    assert build_sessions_changed_payload(SESSION_KEY, "cron_result") == {
        "key": SESSION_KEY,
        "reason": "cron_result",
    }


@pytest.mark.asyncio
async def test_cron_ws_emitter_fans_out_to_topic_and_wildcard_with_error_isolation() -> None:
    topic_conn = _FakeConn()
    wildcard_conn = _FakeConn()
    failing_conn = _FakeConn(fail=True)
    registry = _FakeRegistry(
        {
            "topic": topic_conn,
            "wildcard": wildcard_conn,
            "failing": failing_conn,
        }
    )
    sub_mgr = _FakeSubscriptionManager(
        topic_subscribers={
            "cron:drink": {"topic", "failing"},
            "cron:*": {"wildcard", "topic"},
        }
    )

    emitter = make_cron_ws_emitter(
        subscription_manager=sub_mgr,
        connection_registry_getter=lambda: registry,
    )

    sent = await emitter("cron:drink", "cron.run.finished", {"jobId": "drink"})

    assert sent == 2
    assert topic_conn.events == [("cron.run.finished", {"jobId": "drink"})]
    assert wildcard_conn.events == [("cron.run.finished", {"jobId": "drink"})]
    assert failing_conn.events == []


@pytest.mark.asyncio
async def test_session_forwarder_records_and_notifies_subscribers() -> None:
    message_conn = _FakeConn()
    session_conn = _FakeConn()
    shared_conn = _FakeConn()
    registry = _FakeRegistry(
        {
            "message": message_conn,
            "session": session_conn,
            "shared": shared_conn,
        }
    )
    sub_mgr = _FakeSubscriptionManager(
        message_subscribers={SESSION_KEY: {"message", "shared"}},
        session_subscribers={"session", "shared"},
    )
    session_manager = _FakeSessionManager()
    stream_registry = SessionStreamRegistry(max_events_per_session=5)
    forwarder = make_session_forwarder(
        session_manager=session_manager,
        subscription_manager=sub_mgr,
        connection_registry_getter=lambda: registry,
        stream_registry=stream_registry,
    )

    await forwarder(
        origin_session_key=SESSION_KEY,
        text="drink logged",
        provenance={
            "kind": "cron",
            "source_session_key": CRON_SESSION_KEY,
            "source_tool": "cron:drink",
        },
    )

    assert session_manager.appended == [
        {
            "session_key": SESSION_KEY,
            "role": "assistant",
            "content": "drink logged",
            "provenance": {
                "kind": "cron",
                "source_session_key": CRON_SESSION_KEY,
                "source_tool": "cron:drink",
            },
        }
    ]
    expected_cron_payload = {
        "sessionKey": SESSION_KEY,
        "message": {
            "role": "assistant",
            "text": "drink logged",
            "timestamp": "2026-05-19T00:00:00+00:00",
            "provenanceKind": "cron",
            "provenanceSourceTool": "cron:drink",
            "provenanceSourceSessionKey": CRON_SESSION_KEY,
        },
        "session_key": SESSION_KEY,
        "stream_seq": 1,
    }
    expected_changed_payload = {"key": SESSION_KEY, "reason": "cron_result"}
    assert message_conn.events == [
        ("session.event.cron_result", expected_cron_payload),
        ("sessions.changed", expected_changed_payload),
    ]
    assert session_conn.events == [("sessions.changed", expected_changed_payload)]
    assert shared_conn.events == [
        ("session.event.cron_result", expected_cron_payload),
        ("sessions.changed", expected_changed_payload),
    ]
    assert stream_registry.current_seq(SESSION_KEY) == 1


def test_delivery_chain_factory_wires_gateway_cron_delivery_boundaries() -> None:
    sub_mgr = _FakeSubscriptionManager()
    session_manager = _FakeSessionManager()
    chain = build_cron_delivery_chain(
        channel_manager_ref=lambda: None,
        subscription_manager=sub_mgr,
        session_manager=session_manager,
    )

    assert isinstance(chain, DeliveryChain)
    assert chain._channel_manager_ref is not None
    assert chain._ws_emitter is not None
    assert chain._session_forwarder is not None


def test_boot_delegates_cron_delivery_helpers_to_gateway_boundary() -> None:
    source = boot.__file__ and open(boot.__file__, encoding="utf-8").read()
    tree = ast.parse(source)
    imports = {
        (node.module, alias.name)
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
        for alias in node.names
    }
    top_level_functions = {
        node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    assert (
        "opensquilla.gateway.cron_handler_wiring",
        "register_gateway_cron_handlers",
    ) in imports
    assert (
        "opensquilla.gateway.cron_result_delivery",
        "build_cron_delivery_chain",
    ) not in imports
    assert "build_cron_result_payload" not in top_level_functions
    assert "build_sessions_changed_payload" not in top_level_functions


def test_cron_handler_wiring_owns_delivery_chain_registration_dependency() -> None:
    from opensquilla.gateway import cron_handler_wiring

    source = cron_handler_wiring.__file__ and open(
        cron_handler_wiring.__file__, encoding="utf-8"
    ).read()
    tree = ast.parse(source)
    imports = {
        (node.module, alias.name)
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
        for alias in node.names
    }

    assert (
        "opensquilla.gateway.cron_result_delivery",
        "build_cron_delivery_chain",
    ) in imports
