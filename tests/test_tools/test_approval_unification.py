from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from opensquilla.gateway.approval_queue import get_approval_queue, reset_approval_queue
from opensquilla.sandbox.config import SandboxSettings
from opensquilla.sandbox.integration import configure_runtime, reset_runtime
from opensquilla.tools.builtin import code_exec, shell
from opensquilla.tools.builtin import patch as patch_tool
from opensquilla.tools.types import CallerKind, ToolContext, current_tool_context


def _original_async(fn):
    return fn.__wrapped__.__wrapped__  # type: ignore[attr-defined, no-any-return]


@pytest.fixture(autouse=True)
def _reset_state():
    reset_approval_queue()
    reset_runtime()
    yield
    reset_runtime()
    reset_approval_queue()


@pytest.mark.asyncio
async def test_shell_warnlist_uses_sandbox_gate_without_exec_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, object]] = []

    class _Runtime:
        effective = SimpleNamespace(sandbox_enabled=True)

    async def _fake_gate_action(**kwargs):
        calls.append(("gate", kwargs))
        policy = SimpleNamespace()
        request = SimpleNamespace(cwd="/tmp", action_kind="shell.exec", policy=policy)
        return object(), policy, request

    async def _fake_run_under_backend(request, *, runtime=None):
        calls.append(("backend", request))
        return SimpleNamespace(
            returncode=0,
            stdout="sandboxed\n",
            stderr="",
            backend_notes=(),
        )

    monkeypatch.setattr(shell, "get_runtime", lambda: _Runtime())
    monkeypatch.setattr(shell, "gate_action", _fake_gate_action)
    monkeypatch.setattr(shell, "run_under_backend", _fake_run_under_backend)
    monkeypatch.setattr(
        shell,
        "check_safe_bin",
        lambda command: SimpleNamespace(
            allowed=True,
            needs_approval=True,
            reason="command requires approval",
        ),
    )

    token = current_tool_context.set(
        ToolContext(is_owner=True, caller_kind=CallerKind.CLI, session_key="s1")
    )
    try:
        result = await shell.exec_command("rm x")
    finally:
        current_tool_context.reset(token)

    assert "sandboxed" in result
    assert get_approval_queue().list_pending("exec") == []
    assert [name for name, _ in calls] == ["gate", "backend"]
    hints = calls[0][1]["hints"]  # type: ignore[index]
    assert hints.high_impact is True


@pytest.mark.asyncio
async def test_apply_patch_workspace_escape_uses_sandbox_path_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("old\n", encoding="utf-8")
    configure_runtime(
        SandboxSettings(run_mode="standard", backend="noop", allow_legacy_mode=True),
        workspace=workspace,
    )
    monkeypatch.setattr(patch_tool, "_default_patch_root", lambda: tmp_path.resolve())
    token = current_tool_context.set(
        ToolContext(
            is_owner=True,
            caller_kind=CallerKind.CLI,
            workspace_dir=str(workspace),
            session_key="s1",
        )
    )
    apply_patch = _original_async(patch_tool.apply_patch)
    try:
        result = await apply_patch(
            """*** Begin Patch
*** Update File: outside.txt
@@@ -1,1 +1,1 @@@
-old
+new
*** End Patch"""
        )
    finally:
        current_tool_context.reset(token)

    payload = json.loads(result)
    assert payload["status"] == "approval_required"
    assert payload["approvalKind"] == "sandbox_path"
    assert payload["path"] == str(outside.resolve())
    assert payload["access"] == "rw"
    pending = get_approval_queue().list_pending("exec")
    assert len(pending) == 1
    assert pending[0]["params"]["approvalKind"] == "sandbox_path"
    assert "toolName" not in pending[0]["params"]
    assert outside.read_text(encoding="utf-8") == "old\n"


@pytest.mark.asyncio
async def test_destructive_code_exec_without_runtime_does_not_create_exec_approval() -> None:
    token = current_tool_context.set(
        ToolContext(is_owner=True, caller_kind=CallerKind.CLI, session_key="s1")
    )
    try:
        result = await code_exec.execute_code("import os\nos.remove('target.txt')")
    finally:
        current_tool_context.reset(token)

    payload = json.loads(result)
    assert payload["status"] == "denied"
    assert payload["reason"] == "runtime_unconfigured"
    assert get_approval_queue().list_pending("exec") == []
