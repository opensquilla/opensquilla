"""Gate narrowing: channel-originated UNATTENDED runs can request approval."""

from __future__ import annotations

import asyncio

import pytest

from opensquilla.gateway.approval_queue import get_approval_queue, reset_approval_queue
from opensquilla.sandbox.integration import reset_runtime
from opensquilla.sandbox.intent_cache import reset_intent_cache
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
    reset_intent_cache()
    reset_runtime()
    monkeypatch.setattr(shell, "_sandbox_effectively_off", lambda: True)
    elevate_token = shell._elevate_current_call.set(False)
    yield
    shell._elevate_current_call.reset(elevate_token)
    reset_approval_queue()
    reset_intent_cache()
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
async def test_unattended_channel_with_reachable_owner_enqueues_and_waits() -> None:
    ctx = _channel_ctx(sender_id="owner-1", channel_kind="feishu")
    token = current_tool_context.set(ctx)
    queue = get_approval_queue()
    try:

        elevated_after: list[bool] = []

        async def _call() -> dict | None:
            # _elevate_current_call is a contextvar scoped to this task, so the
            # per-call host grant is captured here (the real caller executes the
            # command in the same task right after this returns).
            result = await shell._check_exec_approval(
                "exec_command",
                "rm target.txt",
                None,
                "command requires approval",
                None,
                False,
            )
            elevated_after.append(shell._elevate_current_call.get())
            return result

        # The call blocks on wait(); a channel run has no retry loop.
        call_task = asyncio.create_task(_call())
        # Give it a moment to enqueue and start waiting.
        for _ in range(50):
            await asyncio.sleep(0.02)
            pending = queue.list_pending("exec")
            if pending:
                break
        assert len(pending) == 1, "channel-originated request should enqueue, not raise"
        entry_params = pending[0]["params"]
        assert entry_params["senderId"] == "owner-1"
        assert entry_params["channelKind"] == "feishu"

        # Resolve as the owner — the blocked call unblocks and grants the call.
        approval_id = pending[0]["id"]
        queue.resolve(approval_id, approved=True, elevated_mode=None)
        result = await asyncio.wait_for(call_task, timeout=5.0)
        assert result is None  # approval granted -> fall through to execution
        assert elevated_after == [True]  # per-call host grant set in the call's task
    finally:
        if not call_task.done():
            call_task.cancel()
        current_tool_context.reset(token)


@pytest.mark.asyncio
async def test_unattended_channel_without_sender_still_raises() -> None:
    ctx = _channel_ctx(sender_id=None, channel_kind="feishu")
    token = current_tool_context.set(ctx)
    queue = get_approval_queue()
    try:
        with pytest.raises(UnsupportedSurfaceError):
            await shell._check_exec_approval(
                "exec_command",
                "rm target.txt",
                None,
                "command requires approval",
                None,
                False,
            )
        assert len(queue.list_pending("exec")) == 0
    finally:
        current_tool_context.reset(token)


@pytest.mark.asyncio
async def test_unattended_non_channel_still_raises() -> None:
    # Cron / subagent style: UNATTENDED with no reachable channel approver.
    ctx = ToolContext(
        is_owner=False,
        caller_kind=CallerKind.CRON,
        interaction_mode=InteractionMode.UNATTENDED,
        session_key="agent:main:cron",
        sender_id="cron-job-1",
    )
    token = current_tool_context.set(ctx)
    queue = get_approval_queue()
    try:
        with pytest.raises(UnsupportedSurfaceError):
            await shell._check_exec_approval(
                "exec_command",
                "rm target.txt",
                None,
                "command requires approval",
                None,
                False,
            )
        assert len(queue.list_pending("exec")) == 0
    finally:
        current_tool_context.reset(token)
