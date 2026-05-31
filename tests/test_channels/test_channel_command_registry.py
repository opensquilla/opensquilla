from __future__ import annotations

import pytest

from opensquilla.channels.command_registry import DEFAULT_COMMAND_REGISTRY
from opensquilla.channels.types import IncomingMessage
from opensquilla.engine.commands import DEFAULT_REGISTRY, Surface
from opensquilla.gateway.protocol import make_error_res, make_ok_res
from opensquilla.gateway.routing import build_channel_route_envelope


def test_channel_command_names_include_usage_and_registry_words() -> None:
    expected = {
        word.lstrip("/").lower()
        for cmd in DEFAULT_REGISTRY.for_surface(Surface.CHANNEL)
        for word in cmd.words()
    }

    assert "usage" in DEFAULT_COMMAND_REGISTRY.command_names
    assert expected <= DEFAULT_COMMAND_REGISTRY.command_names


@pytest.mark.asyncio
async def test_channel_compact_command_uses_short_context_budget_wording() -> None:
    msg = IncomingMessage(sender_id="u1", channel_id="c1", content="/compact")
    envelope = build_channel_route_envelope(
        msg,
        session_key="agent:main:feishu:u1",
        session_prefix="feishu",
        agent_id="main",
    )

    class FakeDispatcher:
        async def dispatch(self, req_id, method, params, ctx):
            return make_ok_res(
                req_id,
                {
                    "key": "agent:main:feishu:u1",
                    "compacted": False,
                    "status": "skipped",
                },
            )

    reply = await DEFAULT_COMMAND_REGISTRY.dispatch(
        envelope=envelope,
        message_content="/compact",
        rpc_dispatcher=FakeDispatcher(),
        context_factory=lambda _envelope: object(),
    )

    assert reply is not None
    assert reply.content == "Already within context budget; no compact was applied."
    assert reply.metadata["command"] == "compact"


@pytest.mark.asyncio
async def test_channel_compact_command_reports_failure_shortly() -> None:
    msg = IncomingMessage(sender_id="u1", channel_id="c1", content="/compact")
    envelope = build_channel_route_envelope(
        msg,
        session_key="agent:main:feishu:u1",
        session_prefix="feishu",
        agent_id="main",
    )

    class FakeDispatcher:
        async def dispatch(self, req_id, method, params, ctx):
            return make_error_res(req_id, "INTERNAL_ERROR", "provider down")

    reply = await DEFAULT_COMMAND_REGISTRY.dispatch(
        envelope=envelope,
        message_content="/compact",
        rpc_dispatcher=FakeDispatcher(),
        context_factory=lambda _envelope: object(),
    )

    assert reply is not None
    assert reply.content == "Compact failed: provider down"
    assert reply.metadata["command"] == "compact"
