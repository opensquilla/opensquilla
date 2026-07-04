"""Regression: a failed websocket send must not abort session event fan-out.

_emit_to_subscribers logs ``emit.send_failed`` when a subscriber's send_event
raises. structlog binds ``event`` as the first positional argument of its log
methods, so passing ``event=`` as a keyword collides and raises TypeError inside
the except handler — which escapes the fan-out loop and (from the turn task)
fails the whole turn. The log call must use a non-reserved key (``ws_event``).
"""

from __future__ import annotations

import types

import pytest

from opensquilla.gateway import rpc_sessions
from opensquilla.gateway import websocket as websocket_mod


class _FailingConn:
    async def send_event(self, event: str, payload=None) -> None:
        raise RuntimeError("client disconnected")


class _FakeRegistry:
    def get(self, conn_id: str) -> _FailingConn:
        return _FailingConn()


class _SubMgr:
    def get_message_subscribers(self, session_key: str) -> set[str]:
        return {"c1"}

    def get_session_subscribers(self) -> set[str]:
        return set()


@pytest.mark.asyncio
async def test_emit_to_subscribers_survives_send_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(websocket_mod, "get_registry", lambda: _FakeRegistry())
    ctx = types.SimpleNamespace(subscription_manager=_SubMgr(), session_manager=None)

    # Must not raise even though the connection's send_event fails and the
    # failure is logged (the log call must not collide with structlog's
    # reserved 'event' positional argument).
    await rpc_sessions._emit_to_subscribers(ctx, "agent:main:s1", "message.chunk", {"x": 1})
