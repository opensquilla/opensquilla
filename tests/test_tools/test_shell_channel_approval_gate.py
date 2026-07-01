"""Channel-originated sandbox approvals keep enough metadata to notify back."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from opensquilla.gateway.approval_queue import get_approval_queue, reset_approval_queue
from opensquilla.sandbox.config import SandboxSettings
from opensquilla.sandbox.integration import configure_runtime, reset_runtime
from opensquilla.tools.builtin import shell
from opensquilla.tools.types import (
    CallerKind,
    InteractionMode,
    ToolContext,
    current_tool_context,
)


@pytest.fixture(autouse=True)
def _reset_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from opensquilla.application import approval_queue as approval_queue_mod

    monkeypatch.setattr(
        approval_queue_mod,
        "_DEFAULT_APPROVAL_QUEUE_PATH",
        tmp_path / "approval_queue.sqlite",
    )
    reset_approval_queue()
    reset_runtime()
    yield
    reset_runtime()
    reset_approval_queue()


@pytest.mark.asyncio
async def test_channel_sandbox_path_approval_records_owner_sender(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    configure_runtime(
        SandboxSettings(run_mode="standard", backend="noop", allow_legacy_mode=True),
        workspace=workspace,
    )
    token = current_tool_context.set(
        ToolContext(
            is_owner=False,
            caller_kind=CallerKind.CHANNEL,
            interaction_mode=InteractionMode.UNATTENDED,
            workspace_dir=str(workspace),
            session_key="agent:main:chat",
            channel_kind="feishu",
            channel_id="oc_demo",
            sender_id="ou_owner",
            run_mode="standard",
        )
    )
    try:
        result = await shell.exec_command("pwd", workdir=str(outside))
    finally:
        current_tool_context.reset(token)

    payload = json.loads(result)
    assert payload["status"] == "approval_required"
    assert payload["approvalKind"] == "sandbox_path"
    assert payload["path"] == str(outside.resolve(strict=False))

    pending = get_approval_queue().list_pending("exec")
    assert len(pending) == 1
    params = pending[0]["params"]
    assert params["approvalKind"] == "sandbox_path"
    assert params["sessionKey"] == "agent:main:chat"
    assert params["senderId"] == "ou_owner"
    assert params["channelKind"] == "feishu"
    assert params["channelId"] == "oc_demo"
    assert "toolName" not in params
