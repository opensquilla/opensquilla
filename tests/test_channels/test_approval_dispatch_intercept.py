"""Owner-only resolution of channel approval actions in dispatch."""

from __future__ import annotations

import asyncio

import pytest

from opensquilla.channels.approval_prompt import bind_short_code, reset_short_codes
from opensquilla.channels.types import IncomingMessage
from opensquilla.gateway.approval_queue import get_approval_queue, reset_approval_queue
from opensquilla.gateway.channel_dispatch import _maybe_resolve_channel_approval


@pytest.fixture(autouse=True)
def _reset_state():
    reset_approval_queue()
    reset_short_codes()
    yield
    reset_approval_queue()
    reset_short_codes()


def _pending_approval(owner_sender_id: str) -> tuple[str, str]:
    queue = get_approval_queue()
    approval_id = queue.request(
        namespace="exec",
        params={
            "toolName": "exec_command",
            "command": "rm target.txt",
            "sessionKey": "agent:main:chat",
            "senderId": owner_sender_id,
            "channelKind": "feishu",
        },
    )
    code = bind_short_code(
        approval_id,
        namespace="exec",
        session_key="agent:main:chat",
        owner_sender_id=owner_sender_id,
    )
    return approval_id, code


def test_non_action_message_is_ignored() -> None:
    msg = IncomingMessage(sender_id="owner", channel_id="c1", content="hello there")
    assert _maybe_resolve_channel_approval(msg=msg, session_key="agent:main:chat") is None


def test_unknown_code_returns_no_pending() -> None:
    msg = IncomingMessage(sender_id="owner", channel_id="c1", content="/approve ZZZZ")
    reply = _maybe_resolve_channel_approval(msg=msg, session_key="agent:main:chat")
    assert reply is not None
    assert "No pending approval ZZZZ" in reply.content


def test_non_owner_cannot_resolve() -> None:
    approval_id, code = _pending_approval(owner_sender_id="owner-1")
    msg = IncomingMessage(sender_id="intruder-2", channel_id="c1", content=f"/approve {code}")

    reply = _maybe_resolve_channel_approval(msg=msg, session_key="agent:main:chat")

    assert reply is not None
    assert "Only the session owner" in reply.content
    # The request must still be unresolved — the non-owner attempt did not flip it.
    assert get_approval_queue().get(approval_id).resolved is False


def test_owner_approve_resolves_and_forces_no_elevation() -> None:
    approval_id, code = _pending_approval(owner_sender_id="owner-1")
    queue = get_approval_queue()
    # A waiter blocked on the approval (mirrors the suspended tool call).
    waited: list[bool] = []

    async def _run() -> None:
        async def _waiter() -> None:
            waited.append(await queue.wait(approval_id, timeout=5.0))

        waiter_task = asyncio.create_task(_waiter())
        await asyncio.sleep(0.05)
        msg = IncomingMessage(
            sender_id="owner-1", channel_id="c1", content=f"/approve {code}"
        )
        reply = _maybe_resolve_channel_approval(msg=msg, session_key="agent:main:chat")
        assert reply is not None
        assert f"Approved {code}" in reply.content
        await asyncio.wait_for(waiter_task, timeout=5.0)

    asyncio.run(_run())

    assert waited == [True]
    entry = queue.get(approval_id)
    assert entry.resolved is True
    assert entry.approved is True
    # Channel approval never grants session-wide elevation.
    assert queue.get_elevated_mode("agent:main:chat") is None
    assert "elevatedMode" not in entry.params


def test_owner_deny_resolves_to_not_approved() -> None:
    approval_id, code = _pending_approval(owner_sender_id="owner-1")
    msg = IncomingMessage(sender_id="owner-1", channel_id="c1", content=f"/deny {code}")

    reply = _maybe_resolve_channel_approval(msg=msg, session_key="agent:main:chat")

    assert reply is not None
    assert f"Denied {code}" in reply.content
    entry = get_approval_queue().get(approval_id)
    assert entry.resolved is True
    assert entry.approved is False
