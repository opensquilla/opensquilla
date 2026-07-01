"""Gate narrowing: channel-originated UNATTENDED runs can request approval.

A channel turn runs UNATTENDED, but when a reachable channel owner started it
the approval must be enqueued (not fail-fast) and stamped with senderId /
channelKind so approval_notify can route a /approve prompt back to that owner.
This is the producer half of the channel approval flow; without it the retained
approval_notify bridge and channel_dispatch /approve command are dead.
"""

from __future__ import annotations

import pytest

from opensquilla.gateway.approval_queue import get_approval_queue, reset_approval_queue
from opensquilla.sandbox.integration import reset_runtime
from opensquilla.tools.builtin import shell
from opensquilla.tools.types import (
    CallerKind,
    InteractionMode,
    ToolContext,
    UnsupportedSurfaceError,
    current_tool_context,
)


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch: pytest.MonkeyPatch):
    reset_approval_queue()
    reset_runtime()
    # Force the sandbox-off shell path: the sandbox gate must not intercept, so
    # the warnlist approval is enqueued through _check_exec_approval.
    monkeypatch.setattr(shell, "_sandbox_effectively_off", lambda: True)
    monkeypatch.setattr(shell, "_host_execution_allowed", lambda: False)
    yield
    reset_approval_queue()
    reset_runtime()


def _channel_ctx(*, sender_id: str | None, channel_kind: str | None) -> ToolContext:
    return ToolContext(
        is_owner=False,
        caller_kind=CallerKind.CHANNEL,
        interaction_mode=InteractionMode.UNATTENDED,
        session_key="agent:main:chat",
        channel_kind=channel_kind,
        channel_id="c1",
        sender_id=sender_id,
    )


@pytest.mark.asyncio
async def test_unattended_channel_with_reachable_owner_enqueues_with_origin() -> None:
    token = current_tool_context.set(_channel_ctx(sender_id="owner-1", channel_kind="feishu"))
    try:
        result = await shell._check_exec_approval(
            tool_name="exec_command",
            command="rm target.txt",
            workdir=None,
            warning="requires approval",
            approval_id=None,
            background=False,
        )
    finally:
        current_tool_context.reset(token)

    # Channel-originated request should enqueue, not raise.
    assert result is not None
    pending = get_approval_queue().list_pending("exec")
    assert len(pending) == 1
    params = pending[0]["params"]
    assert params["senderId"] == "owner-1"
    assert params["channelKind"] == "feishu"


@pytest.mark.asyncio
async def test_unattended_channel_without_sender_still_raises() -> None:
    token = current_tool_context.set(_channel_ctx(sender_id=None, channel_kind="feishu"))
    try:
        with pytest.raises(UnsupportedSurfaceError):
            await shell._check_exec_approval(
                tool_name="exec_command",
                command="rm target.txt",
                workdir=None,
                warning="requires approval",
                approval_id=None,
                background=False,
            )
    finally:
        current_tool_context.reset(token)
    assert get_approval_queue().list_pending("exec") == []


@pytest.mark.asyncio
async def test_unattended_non_channel_still_raises() -> None:
    ctx = ToolContext(
        is_owner=False,
        caller_kind=CallerKind.AGENT,
        interaction_mode=InteractionMode.UNATTENDED,
        session_key="agent:main:cron",
    )
    token = current_tool_context.set(ctx)
    try:
        with pytest.raises(UnsupportedSurfaceError):
            await shell._check_exec_approval(
                tool_name="exec_command",
                command="rm target.txt",
                workdir=None,
                warning="requires approval",
                approval_id=None,
                background=False,
            )
    finally:
        current_tool_context.reset(token)
    assert get_approval_queue().list_pending("exec") == []
