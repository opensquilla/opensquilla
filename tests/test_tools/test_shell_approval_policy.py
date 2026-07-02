from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from opensquilla.gateway.approval_queue import get_approval_queue, reset_approval_queue
from opensquilla.sandbox.config import SandboxSettings
from opensquilla.sandbox.integration import configure_runtime, reset_runtime
from opensquilla.tools.builtin import code_exec, filesystem, shell
from opensquilla.tools.builtin.code_exec import execute_code
from opensquilla.tools.builtin.shell_policy import PolicyResult
from opensquilla.tools.types import (
    CallerKind,
    InteractionMode,
    ToolContext,
    ToolError,
    current_tool_context,
)


@pytest.fixture(autouse=True)
def reset_approval_state():
    reset_approval_queue()
    reset_runtime()
    token = current_tool_context.set(
        ToolContext(is_owner=True, caller_kind=CallerKind.CLI, session_key="agent:main:test")
    )
    yield
    current_tool_context.reset(token)
    reset_approval_queue()
    reset_runtime()


def test_audit_command_preserves_long_commands_until_cap() -> None:
    command = "rm " + ("x" * 120)
    assert shell._audit_command(command) == command

    huge = "rm " + ("x" * 5000)
    audited = shell._audit_command(huge)
    assert len(audited) > 80
    assert audited.endswith("...[truncated]")


@pytest.mark.asyncio
async def test_exec_approval_deny_pattern_blocks_shell_command(tmp_path: Path) -> None:
    get_approval_queue().set_settings("prompt", deny_patterns=["rm *"])

    result = await shell.exec_command("rm target.txt", workdir=str(tmp_path))
    payload = json.loads(result)

    assert payload["status"] == "approval_denied"
    assert payload["command"] == "rm target.txt"
    assert get_approval_queue().list_pending("exec") == []


@pytest.mark.asyncio
async def test_exec_approval_deny_pattern_does_not_depend_on_warnlist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    get_approval_queue().set_settings("prompt", deny_patterns=["git status"])
    monkeypatch.setattr(
        shell,
        "check_safe_bin",
        lambda _command: PolicyResult(allowed=True, reason="", needs_approval=False),
    )

    result = await shell.exec_command("git status", workdir=str(tmp_path))
    payload = json.loads(result)

    assert payload["status"] == "approval_denied"
    assert payload["command"] == "git status"


@pytest.mark.asyncio
async def test_full_host_access_warnlisted_exec_skips_approval_and_uses_host(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx = current_tool_context.get()
    assert ctx is not None
    ctx.run_mode = "full"
    get_approval_queue().set_settings("auto-deny")
    calls: list[str] = []

    async def fake_host_execution(*args: object, **kwargs: object) -> str:
        calls.append("host")
        return "exit_code=0\nhost\n"

    monkeypatch.setattr(shell, "_run_host_shell_command", fake_host_execution)
    monkeypatch.setattr(
        shell,
        "check_safe_bin",
        lambda command: PolicyResult(
            allowed=True,
            reason=f"command requires approval: {command}",
            needs_approval=True,
        ),
    )

    result = await shell.exec_command("pip install requests", workdir=str(tmp_path))

    assert result == "exit_code=0\nhost\n"
    assert calls == ["host"]
    assert get_approval_queue().list_pending("exec") == []


@pytest.mark.asyncio
async def test_sandbox_disabled_warnlisted_exec_skips_approval_and_uses_host(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx = current_tool_context.get()
    assert ctx is not None
    ctx.run_mode = "standard"
    ctx.workspace_dir = str(tmp_path)
    configure_runtime(
        SandboxSettings(sandbox=False, security_grading=False),
        workspace=tmp_path,
    )
    get_approval_queue().set_settings("auto-deny")
    calls: list[str] = []

    async def fake_host_execution(*args: object, **kwargs: object) -> str:
        calls.append("host")
        return "exit_code=0\nhost\n"

    monkeypatch.setattr(shell, "_run_host_shell_command", fake_host_execution)
    monkeypatch.setattr(
        shell,
        "check_safe_bin",
        lambda command: PolicyResult(
            allowed=True,
            reason=f"command requires approval: {command}",
            needs_approval=True,
        ),
    )

    result = await shell.exec_command("pip install requests", workdir=str(tmp_path))

    assert result == "exit_code=0\nhost\n"
    assert calls == ["host"]
    assert get_approval_queue().list_pending("exec") == []


@pytest.mark.asyncio
async def test_warnlisted_exec_allow_pattern_skips_prompt_when_sandbox_enabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx = current_tool_context.get()
    assert ctx is not None
    ctx.workspace_dir = str(tmp_path)
    get_approval_queue().set_settings(
        "prompt",
        allow_patterns=["pip install requests"],
    )
    configure_runtime(
        SandboxSettings(
            sandbox=True,
            security_grading=True,
            backend="noop",
            allow_legacy_mode=True,
        ),
        workspace=tmp_path,
    )
    calls: list[tuple[str, object]] = []

    async def fake_gate_action(**kwargs: object) -> tuple[object, object, object]:
        calls.append(("gate", kwargs))
        policy = SimpleNamespace(network=None)
        request = SimpleNamespace(cwd=tmp_path, action_kind="shell.exec", policy=policy)
        return object(), policy, request

    async def fake_sandbox(request: object, *, runtime: object = None) -> object:
        calls.append(("backend", request))
        return SimpleNamespace(
            returncode=0,
            stdout="sandboxed\n",
            stderr="",
            timed_out=False,
            backend_notes=(),
        )

    monkeypatch.setattr(shell, "gate_action", fake_gate_action)
    monkeypatch.setattr(shell, "run_under_backend", fake_sandbox)
    monkeypatch.setattr(
        shell,
        "check_safe_bin",
        lambda command: PolicyResult(
            allowed=True,
            reason=f"command requires approval: {command}",
            needs_approval=True,
        ),
    )

    result = await shell.exec_command("pip install requests", workdir=str(tmp_path))

    assert "sandboxed" in result
    assert [name for name, _ in calls] == ["gate", "backend"]
    assert get_approval_queue().list_pending("exec") == []


@pytest.mark.asyncio
async def test_warnlisted_exec_allow_pattern_runs_without_approval_when_no_sandbox_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    get_approval_queue().set_settings(
        "prompt",
        allow_patterns=["pip install requests"],
    )
    calls: list[str] = []

    async def fake_host_execution(*args: object, **kwargs: object) -> str:
        calls.append("host")
        return "exit_code=0\nhost\n"

    monkeypatch.setattr(shell, "_run_host_shell_command", fake_host_execution)
    monkeypatch.setattr(
        shell,
        "check_safe_bin",
        lambda command: PolicyResult(
            allowed=True,
            reason=f"command requires approval: {command}",
            needs_approval=True,
        ),
    )

    result = await shell.exec_command("pip install requests", workdir=str(tmp_path))

    assert result == "exit_code=0\nhost\n"
    assert get_approval_queue().list_pending("exec") == []
    assert calls == ["host"]


@pytest.mark.asyncio
async def test_warnlisted_exec_prompt_runs_without_approval_when_no_sandbox_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    get_approval_queue().set_settings("prompt")
    calls: list[str] = []

    async def fake_host_execution(*args: object, **kwargs: object) -> str:
        calls.append("host")
        return "exit_code=0\nhost\n"

    monkeypatch.setattr(shell, "_run_host_shell_command", fake_host_execution)
    monkeypatch.setattr(
        shell,
        "check_safe_bin",
        lambda command: PolicyResult(
            allowed=True,
            reason=f"command requires approval: {command}",
            needs_approval=True,
        ),
    )

    result = await shell.exec_command("pip install requests", workdir=str(tmp_path))

    assert result == "exit_code=0\nhost\n"
    assert get_approval_queue().list_pending("exec") == []
    assert calls == ["host"]


@pytest.mark.asyncio
async def test_warnlisted_exec_auto_approve_runs_without_approval_when_no_sandbox_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    get_approval_queue().set_settings("auto-approve")
    calls: list[str] = []

    async def fake_host_execution(*args: object, **kwargs: object) -> str:
        calls.append("host")
        return "exit_code=0\nhost\n"

    monkeypatch.setattr(shell, "_run_host_shell_command", fake_host_execution)
    monkeypatch.setattr(
        shell,
        "check_safe_bin",
        lambda command: PolicyResult(
            allowed=True,
            reason=f"command requires approval: {command}",
            needs_approval=True,
        ),
    )

    result = await shell.exec_command("pip install requests", workdir=str(tmp_path))

    assert result == "exit_code=0\nhost\n"
    assert get_approval_queue().list_pending("exec") == []
    assert calls == ["host"]


@pytest.mark.asyncio
async def test_warnlisted_exec_unattended_runs_without_approval_when_no_sandbox_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx = current_tool_context.get()
    assert ctx is not None
    ctx.interaction_mode = InteractionMode.UNATTENDED
    get_approval_queue().set_settings("prompt")
    calls: list[str] = []

    async def fake_host_execution(*args: object, **kwargs: object) -> str:
        calls.append("host")
        return "exit_code=0\nhost\n"

    monkeypatch.setattr(shell, "_run_host_shell_command", fake_host_execution)
    monkeypatch.setattr(
        shell,
        "check_safe_bin",
        lambda command: PolicyResult(
            allowed=True,
            reason=f"command requires approval: {command}",
            needs_approval=True,
        ),
    )

    result = await shell.exec_command("pip install requests", workdir=str(tmp_path))

    assert result == "exit_code=0\nhost\n"
    assert calls == ["host"]
    assert get_approval_queue().list_pending("exec") == []


@pytest.mark.asyncio
async def test_destructive_code_exec_uses_sandbox_gate_when_runtime_enabled(
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
    calls: list[tuple[str, object]] = []

    async def fake_gate_action(**kwargs):
        calls.append(("gate", kwargs))
        policy = SimpleNamespace(network=None)
        request = SimpleNamespace(cwd=tmp_path, action_kind="code.exec", policy=policy)
        return object(), policy, request

    async def fake_sandbox(request: object, *, runtime: object = None) -> object:
        calls.append(("backend", request))
        return SimpleNamespace(
            returncode=0,
            stdout="sandboxed\n",
            stderr="",
            timed_out=False,
            backend_notes=(),
        )

    monkeypatch.setattr(code_exec, "gate_action", fake_gate_action)
    monkeypatch.setattr(code_exec, "run_under_backend", fake_sandbox)

    result = await execute_code("import os\nos.remove('target.txt')")
    payload = json.loads(result)

    assert payload["exit_code"] == 0
    assert payload["stdout"] == "sandboxed\n"
    assert [name for name, _ in calls] == ["gate", "backend"]
    hints = calls[0][1]["hints"]  # type: ignore[index]
    assert hints.high_impact is True
    assert target.exists()
    assert get_approval_queue().list_pending("exec") == []


@pytest.mark.asyncio
async def test_warnlist_background_process_uses_sandbox_gate_when_runtime_enabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx = current_tool_context.get()
    assert ctx is not None
    ctx.workspace_dir = str(tmp_path)
    configure_runtime(
        SandboxSettings(
            sandbox=True,
            security_grading=True,
            backend="noop",
            allow_legacy_mode=True,
        ),
        workspace=tmp_path,
    )
    calls: list[tuple[str, object]] = []

    class _FakeStream:
        async def read(self, size: int) -> bytes:
            return b""

    class _FakeProcess:
        stdout = _FakeStream()
        stdin = None
        returncode = 0

        async def wait(self) -> int:
            return 0

    async def fake_gate_action(**kwargs):
        calls.append(("gate", kwargs))
        policy = SimpleNamespace(network=None, network_proxy=None)
        request = SimpleNamespace(cwd=tmp_path, action_kind="shell.background", policy=policy)
        return object(), policy, request

    async def fake_sandbox_spawn(*args: object, **kwargs: object) -> object:
        calls.append(("backend", kwargs.get("request")))
        return shell._SpawnedBackgroundProcess(process=_FakeProcess())  # type: ignore[arg-type]

    monkeypatch.setattr(shell, "gate_action", fake_gate_action)
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

    result = await shell.background_process("rm target.txt", workdir=str(tmp_path))

    assert "status: running" in result
    session_id = result.splitlines()[0].split("=", 1)[1]
    session = shell._bg_sessions[session_id]
    assert session.collector_task is not None
    await session.collector_task
    assert [name for name, _ in calls] == ["gate", "backend"]
    hints = calls[0][1]["hints"]  # type: ignore[index]
    assert hints.high_impact is True
    assert get_approval_queue().list_pending("exec") == []


@pytest.mark.asyncio
async def test_outside_workspace_write_blocks_without_sandbox_path_approval(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    ctx = current_tool_context.get()
    assert ctx is not None
    ctx.interaction_mode = InteractionMode.UNATTENDED
    ctx.workspace_dir = str(workspace)

    write_file = filesystem.write_file.__wrapped__.__wrapped__  # type: ignore[attr-defined]
    payload = json.loads(await write_file(str(outside), "ok"))

    assert payload["status"] == "blocked"
    assert payload["reason"] == "outside_workspace"
    assert not outside.exists()
    assert get_approval_queue().list_pending("exec") == []


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
    assert get_approval_queue().list_pending("exec") == []


@pytest.mark.asyncio
async def test_workspace_lockdown_allows_configured_scratch_dir_write(
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

    result = await filesystem._gate_out_of_workspace_write(
        "write_file",
        target.resolve(strict=False),
        str(target),
        None,
    )

    assert result is None
    assert not target.exists()
    assert get_approval_queue().list_pending("exec") == []


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
    assert get_approval_queue().list_pending("exec") == []


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

    result = await shell.exec_command(f"echo ok > {outside}", workdir=str(workspace))
    payload = json.loads(result)

    assert payload["status"] == "blocked"
    assert payload["reason"] == "workspace_lockdown"


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

    result = await shell.exec_command("echo ok > reports/out.txt", workdir=str(workspace))

    payload = json.loads(result)
    assert payload["status"] == "blocked"
    assert payload["reason"] == "workspace_write_deny"
    assert payload["matched_pattern"] == "reports/*.txt"


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

    result = await shell.exec_command("rm ~/.ssh/id_rsa")
    payload = json.loads(result)

    assert payload["status"] == "blocked"
    assert payload["reason"] == "sensitive_path"
    assert shell.full_host_access_active() is False


@pytest.mark.asyncio
async def test_bypass_does_not_override_safe_bin_hard_denies() -> None:
    ctx = current_tool_context.get()
    assert ctx is not None
    ctx.elevated = "bypass"

    with pytest.raises(ToolError, match="command blocked by policy"):
        await shell.exec_command("Clear-Disk")
