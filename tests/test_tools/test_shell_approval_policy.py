from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from opensquilla.gateway.approval_queue import get_approval_queue, reset_approval_queue
from opensquilla.sandbox.config import SandboxSettings
from opensquilla.sandbox.integration import configure_runtime, reset_runtime
from opensquilla.sandbox.intent_cache import get_intent_cache, reset_intent_cache
from opensquilla.tools.builtin import code_exec, filesystem, shell
from opensquilla.tools.builtin.code_exec import execute_code
from opensquilla.tools.builtin.shell_policy import PolicyResult
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
async def test_elevated_bypass_prompts_when_sandbox_off() -> None:
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

    assert result is not None
    assert result["status"] == "approval_required"
    assert shell._elevate_current_call.get() is False


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
async def test_elevated_full_skips_prompt_without_host_once_flag_when_sandbox_off() -> None:
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
    assert shell._host_execution_allowed() is True
    assert shell._elevate_current_call.get() is False


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
async def test_unattended_bypass_with_sandbox_off_fails_fast_without_pending_approval() -> None:
    ctx = current_tool_context.get()
    assert ctx is not None
    ctx.interaction_mode = InteractionMode.UNATTENDED
    ctx.elevated = "bypass"
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

    assert shell._elevate_current_call.get() is False
    assert len(queue.list_pending("exec")) == 0


@pytest.mark.asyncio
async def test_unattended_bypass_with_sandbox_off_blocks_destructive_code_exec(
    tmp_path: Path,
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

    with pytest.raises(UnsupportedSurfaceError):
        await execute_code("import os\nos.remove('target.txt')")

    assert target.exists()
    assert len(get_approval_queue().list_pending("exec")) == 0


@pytest.mark.asyncio
async def test_approved_destructive_code_exec_uses_sandbox_when_sandbox_enabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx = current_tool_context.get()
    assert ctx is not None
    ctx.workspace_dir = str(tmp_path)
    target = tmp_path / "target.txt"
    target.write_text("delete me", encoding="utf-8")
    configure_runtime(
        SandboxSettings(
            sandbox=True,
            security_grading=True,
            backend="noop",
            allow_legacy_mode=True,
        ),
        workspace=tmp_path,
    )
    sandbox_calls: list[object] = []

    async def fake_sandbox(request: object, *, runtime: object = None) -> object:
        sandbox_calls.append(request)
        return SimpleNamespace(
            returncode=0,
            stdout="sandboxed\n",
            stderr="",
            timed_out=False,
            backend_notes=(),
        )

    monkeypatch.setattr(code_exec, "run_under_backend", fake_sandbox)

    code = "import os\nos.remove('target.txt')"
    pending = json.loads(await execute_code(code))
    assert pending["status"] == "approval_required"
    approval_id = str(pending["approval_id"])
    get_approval_queue().resolve(approval_id, approved=True)

    result = await execute_code(code, approval_id=approval_id)
    payload = json.loads(result)

    assert payload["exit_code"] == 0
    assert payload["stdout"] == "sandboxed\n"
    assert sandbox_calls
    assert target.exists()
    assert shell._elevate_current_call.get() is False


@pytest.mark.asyncio
async def test_approved_background_process_uses_sandbox_when_sandbox_enabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx = current_tool_context.get()
    assert ctx is not None
    ctx.workspace_dir = str(tmp_path)
    target = tmp_path / "target.txt"
    target.write_text("delete me", encoding="utf-8")
    configure_runtime(
        SandboxSettings(
            sandbox=True,
            security_grading=True,
            backend="noop",
            allow_legacy_mode=True,
        ),
        workspace=tmp_path,
    )

    sandbox_calls: list[object] = []

    class _FakeStream:
        async def read(self, size: int) -> bytes:
            return b""

    class _FakeProcess:
        stdout = _FakeStream()
        stdin = None
        returncode = 0

        async def wait(self) -> int:
            return 0

    async def fake_sandbox_spawn(*args: object, **kwargs: object) -> object:
        sandbox_calls.append(kwargs.get("request"))
        return shell._SpawnedBackgroundProcess(process=_FakeProcess())  # type: ignore[arg-type]

    monkeypatch.setattr(shell, "_spawn_sandboxed_background_process", fake_sandbox_spawn)
    monkeypatch.setattr(
        shell,
        "check_safe_bin",
        lambda command: PolicyResult(
            allowed=True,
            reason=f"command requires approval: {command}",
            needs_approval=True,
        ),
    )

    pending = json.loads(await shell.background_process("rm target.txt", workdir=str(tmp_path)))
    assert pending["status"] == "approval_required"
    approval_id = str(pending["approval_id"])
    get_approval_queue().resolve(approval_id, approved=True)

    result = await shell.background_process(
        "rm target.txt",
        workdir=str(tmp_path),
        timeout=5,
        approval_id=approval_id,
    )

    assert "status: running" in result
    session_id = result.splitlines()[0].split("=", 1)[1]
    session = shell._bg_sessions[session_id]
    assert session.collector_task is not None
    await session.collector_task
    assert sandbox_calls
    assert target.exists()
    assert shell._elevate_current_call.get() is False


@pytest.mark.asyncio
async def test_unattended_bypass_with_sandbox_off_blocks_outside_workspace_write(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    ctx = current_tool_context.get()
    assert ctx is not None
    ctx.interaction_mode = InteractionMode.UNATTENDED
    ctx.elevated = "bypass"
    ctx.workspace_dir = str(workspace)

    write_file = filesystem.write_file.__wrapped__.__wrapped__  # type: ignore[attr-defined]
    with pytest.raises(UnsupportedSurfaceError):
        await write_file(str(outside), "ok")

    assert not outside.exists()
    assert len(get_approval_queue().list_pending("exec")) == 0


@pytest.mark.asyncio
async def test_workspace_lockdown_blocks_outside_workspace_write_even_with_bypass(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    ctx = current_tool_context.get()
    assert ctx is not None
    ctx.interaction_mode = InteractionMode.UNATTENDED
    ctx.elevated = "bypass"
    ctx.workspace_dir = str(workspace)
    ctx.workspace_lockdown = True  # type: ignore[attr-defined]

    write_file = filesystem.write_file.__wrapped__.__wrapped__  # type: ignore[attr-defined]
    with pytest.raises(ToolError, match="workspace lockdown"):
        await write_file(str(outside), "ok")

    assert not outside.exists()
    assert len(get_approval_queue().list_pending("exec")) == 0


@pytest.mark.asyncio
async def test_unattended_bypass_with_sandbox_off_blocks_configured_scratch_dir_write(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    scratch = tmp_path / "scratch"
    workspace.mkdir()
    scratch.mkdir()
    target = scratch / "debug.py"
    ctx = current_tool_context.get()
    assert ctx is not None
    ctx.interaction_mode = InteractionMode.UNATTENDED
    ctx.elevated = "bypass"
    ctx.workspace_dir = str(workspace)
    ctx.scratch_dir = str(scratch)  # type: ignore[attr-defined]
    ctx.workspace_lockdown = True  # type: ignore[attr-defined]

    write_file = filesystem.write_file.__wrapped__.__wrapped__  # type: ignore[attr-defined]
    with pytest.raises(UnsupportedSurfaceError):
        await write_file(str(target), "print('ok')")

    assert not target.exists()
    assert len(get_approval_queue().list_pending("exec")) == 0


@pytest.mark.asyncio
async def test_workspace_write_deny_globs_block_file_write(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "blocked" / "generated.txt"
    ctx = current_tool_context.get()
    assert ctx is not None
    ctx.interaction_mode = InteractionMode.UNATTENDED
    ctx.elevated = "bypass"
    ctx.workspace_dir = str(workspace)
    ctx.workspace_write_deny_globs = ["blocked/**"]  # type: ignore[attr-defined]

    write_file = filesystem.write_file.__wrapped__.__wrapped__  # type: ignore[attr-defined]
    with pytest.raises(ToolError, match="workspace write deny policy"):
        await write_file(str(target), "nope")

    assert not target.exists()
    assert len(get_approval_queue().list_pending("exec")) == 0


def test_tool_definitions_include_scratch_guidance_when_configured(tmp_path: Path) -> None:
    from opensquilla.tools.registry import get_default_registry

    scratch = tmp_path / "scratch"
    ctx = ToolContext(is_owner=True, scratch_dir=str(scratch))

    tools = get_default_registry().to_tool_definitions(ctx)
    descriptions = {tool.name: tool.description for tool in tools}

    assert str(scratch) in descriptions["exec_command"]
    assert str(scratch) in descriptions["write_file"]


@pytest.mark.asyncio
async def test_workspace_lockdown_blocks_obvious_outside_shell_redirection(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    ctx = current_tool_context.get()
    assert ctx is not None
    ctx.interaction_mode = InteractionMode.UNATTENDED
    ctx.elevated = "bypass"
    ctx.workspace_dir = str(workspace)
    ctx.workspace_lockdown = True  # type: ignore[attr-defined]

    result = await shell._check_exec_approval(
        "exec_command",
        f"echo ok > {outside}",
        str(workspace),
        "command requires approval",
        None,
        False,
    )

    assert result is not None
    assert result["status"] == "blocked"
    assert result["reason"] == "workspace_lockdown"


@pytest.mark.asyncio
async def test_workspace_write_deny_globs_block_shell_redirection(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    ctx = current_tool_context.get()
    assert ctx is not None
    ctx.interaction_mode = InteractionMode.UNATTENDED
    ctx.elevated = "bypass"
    ctx.workspace_dir = str(workspace)
    ctx.workspace_write_deny_globs = ["reports/*.txt"]  # type: ignore[attr-defined]

    result = await shell._check_exec_approval(
        "exec_command",
        "echo ok > reports/out.txt",
        str(workspace),
        "command requires approval",
        None,
        False,
    )

    assert result is not None
    assert result["status"] == "blocked"
    assert result["reason"] == "workspace_write_deny"
    assert result["matched_pattern"] == "reports/*.txt"


@pytest.mark.asyncio
async def test_workspace_write_deny_globs_block_direct_shell_command(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "reports" / "out.txt"
    ctx = current_tool_context.get()
    assert ctx is not None
    ctx.interaction_mode = InteractionMode.UNATTENDED
    ctx.elevated = "bypass"
    ctx.workspace_dir = str(workspace)
    ctx.workspace_write_deny_globs = ["reports/*.txt"]  # type: ignore[attr-defined]

    result = await shell.exec_command("echo ok > reports/out.txt", workdir=str(workspace))

    payload = json.loads(result)
    assert payload["status"] == "blocked"
    assert payload["reason"] == "workspace_write_deny"
    assert not target.exists()


@pytest.mark.asyncio
async def test_workspace_write_deny_globs_inspect_shell_stdin(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    ctx = current_tool_context.get()
    assert ctx is not None
    ctx.interaction_mode = InteractionMode.UNATTENDED
    ctx.elevated = "bypass"
    ctx.workspace_dir = str(workspace)
    ctx.workspace_write_deny_globs = ["reports/*.txt"]  # type: ignore[attr-defined]

    result = await shell.exec_command(
        "sh",
        workdir=str(workspace),
        stdin="mkdir -p reports\necho secret > reports/out.txt\n",
    )

    payload = json.loads(result)
    assert payload["status"] == "blocked"
    assert payload["reason"] == "workspace_write_deny"
    assert payload["matched_pattern"] == "reports/*.txt"


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
