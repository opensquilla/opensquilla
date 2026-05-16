from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from opensquilla.application.approval_queue import get_approval_queue, reset_approval_queue
from opensquilla.application.intent_cache import get_intent_cache, reset_intent_cache
from opensquilla.sandbox.config import SandboxSettings
from opensquilla.sandbox.integration import configure_runtime, reset_runtime
from opensquilla.tools.builtin import code_exec, filesystem, shell
from opensquilla.tools.builtin.code_exec import execute_code
from opensquilla.tools.types import (
    CallerKind,
    InteractionMode,
    ToolContext,
    ToolError,
    UnsupportedSurfaceError,
    current_tool_context,
)


@pytest.fixture(autouse=True)
def reset_approval_state(monkeypatch: pytest.MonkeyPatch):
    reset_approval_queue()
    reset_intent_cache()
    reset_runtime()
    monkeypatch.setattr(shell, "_sandbox_effectively_off", lambda: True)
    elevate_token = shell._elevate_current_call.set(False)
    token = current_tool_context.set(
        ToolContext(is_owner=True, caller_kind=CallerKind.CLI, session_key="agent:main:test")
    )
    yield
    current_tool_context.reset(token)
    shell._elevate_current_call.reset(elevate_token)
    reset_approval_queue()
    reset_intent_cache()
    reset_runtime()


@pytest.mark.asyncio
async def test_sandbox_off_forces_prompt_over_global_auto_approve() -> None:
    queue = get_approval_queue()
    queue.set_settings("auto-approve")

    result = await shell._check_exec_approval(
        "exec_command",
        "rm target.txt",
        None,
        "command requires approval",
        None,
        True,
    )

    assert result is not None
    assert result["status"] == "approval_required"
    assert len(queue.list_pending("exec")) == 1


@pytest.mark.asyncio
async def test_elevated_bypass_skips_prompt_even_when_sandbox_off() -> None:
    ctx = current_tool_context.get()
    assert ctx is not None
    ctx.elevated = "bypass"

    result = await shell._check_exec_approval(
        "exec_command",
        "rm target.txt",
        None,
        "command requires approval",
        None,
        True,
    )

    assert result is None
    assert shell._elevate_current_call.get() is True


@pytest.mark.asyncio
async def test_sandbox_off_forces_prompt_over_cached_intent() -> None:
    get_intent_cache().record("rm target.txt")

    result = await shell._check_exec_approval(
        "exec_command",
        "rm target.txt",
        None,
        "command requires approval",
        None,
        True,
    )

    assert result is not None
    assert result["status"] == "approval_required"
    assert shell._elevate_current_call.get() is False


@pytest.mark.asyncio
async def test_elevated_full_remains_explicit_override_when_sandbox_off() -> None:
    ctx = current_tool_context.get()
    assert ctx is not None
    ctx.elevated = "full"

    result = await shell._check_exec_approval(
        "exec_command",
        "rm target.txt",
        None,
        "command requires approval",
        None,
        True,
    )

    assert result is None
    assert shell._elevate_current_call.get() is True


def test_audit_command_preserves_long_commands_until_cap() -> None:
    command = "rm " + ("x" * 120)
    assert shell._audit_command(command) == command

    huge = "rm " + ("x" * 5000)
    audited = shell._audit_command(huge)
    assert len(audited) > 80
    assert audited.endswith("...[truncated]")


@pytest.mark.asyncio
async def test_unattended_warnlist_shell_fails_fast_without_pending_exec_approval() -> None:
    ctx = current_tool_context.get()
    assert ctx is not None
    ctx.interaction_mode = InteractionMode.UNATTENDED
    queue = get_approval_queue()

    with pytest.raises(UnsupportedSurfaceError):
        await shell._check_exec_approval(
            "exec_command",
            "rm target.txt",
            None,
            "command requires approval",
            None,
            True,
        )

    assert len(queue.list_pending("exec")) == 0


@pytest.mark.asyncio
async def test_unattended_auto_deny_preserves_policy_denial_without_pending_approval() -> None:
    ctx = current_tool_context.get()
    assert ctx is not None
    ctx.interaction_mode = InteractionMode.UNATTENDED
    queue = get_approval_queue()
    queue.set_settings("auto-deny")

    result = await shell._check_exec_approval(
        "exec_command",
        "rm target.txt",
        None,
        "command requires approval",
        None,
        True,
    )

    assert result is not None
    assert result["status"] == "approval_denied"
    assert len(queue.list_pending("exec")) == 0


@pytest.mark.asyncio
async def test_unattended_destructive_code_exec_fails_fast_without_pending_exec_approval() -> None:
    ctx = current_tool_context.get()
    assert ctx is not None
    ctx.interaction_mode = InteractionMode.UNATTENDED
    queue = get_approval_queue()

    with pytest.raises(UnsupportedSurfaceError):
        await execute_code("import os\nos.remove('target.txt')")

    assert len(queue.list_pending("exec")) == 0


@pytest.mark.asyncio
async def test_unattended_bypass_allows_warnlist_shell_without_pending_approval() -> None:
    ctx = current_tool_context.get()
    assert ctx is not None
    ctx.interaction_mode = InteractionMode.UNATTENDED
    ctx.elevated = "bypass"
    queue = get_approval_queue()

    result = await shell._check_exec_approval(
        "exec_command",
        "rm target.txt",
        None,
        "command requires approval",
        None,
        True,
    )

    assert result is None
    assert shell._elevate_current_call.get() is True
    assert len(queue.list_pending("exec")) == 0


@pytest.mark.asyncio
async def test_unattended_bypass_allows_destructive_code_exec(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx = current_tool_context.get()
    assert ctx is not None
    ctx.interaction_mode = InteractionMode.UNATTENDED
    ctx.elevated = "bypass"
    ctx.workspace_dir = str(tmp_path)
    target = tmp_path / "target.txt"
    target.write_text("delete me", encoding="utf-8")
    configure_runtime(
        SandboxSettings(sandbox=False, security_grading=False, allow_legacy_mode=True),
        workspace=tmp_path,
    )
    monkeypatch.setattr(
        code_exec,
        "_resolve_python_bin",
        lambda *, sandbox_enabled: sys.executable,
    )

    result = await execute_code("import os\nos.remove('target.txt')")
    payload = json.loads(result)

    assert payload["exit_code"] == 0
    assert not target.exists()
    assert len(get_approval_queue().list_pending("exec")) == 0


@pytest.mark.asyncio
async def test_unattended_bypass_allows_outside_workspace_write(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    ctx = current_tool_context.get()
    assert ctx is not None
    ctx.interaction_mode = InteractionMode.UNATTENDED
    ctx.elevated = "bypass"
    ctx.workspace_dir = str(workspace)

    write_file = filesystem.write_file.__wrapped__.__wrapped__  # type: ignore[attr-defined]
    result = await write_file(str(outside), "ok")

    assert result.startswith("Written 2 bytes to ")
    assert outside.read_text(encoding="utf-8") == "ok"
    assert len(get_approval_queue().list_pending("exec")) == 0


@pytest.mark.asyncio
async def test_bypass_still_blocks_sensitive_shell_targets() -> None:
    ctx = current_tool_context.get()
    assert ctx is not None
    ctx.elevated = "bypass"

    result = await shell._check_exec_approval(
        "exec_command",
        "rm ~/.ssh/id_rsa",
        None,
        "command requires approval",
        None,
        True,
    )

    assert result is not None
    assert result["status"] == "blocked"
    assert result["reason"] == "sensitive_path"
    assert shell._elevate_current_call.get() is False


@pytest.mark.asyncio
async def test_bypass_does_not_override_safe_bin_hard_denies() -> None:
    ctx = current_tool_context.get()
    assert ctx is not None
    ctx.elevated = "bypass"

    with pytest.raises(ToolError, match="command blocked by policy"):
        await shell.exec_command("Clear-Disk")
