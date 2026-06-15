from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from opensquilla.tools.types import CallerKind, ToolContext, current_tool_context


def _windows_runtime() -> SimpleNamespace:
    return SimpleNamespace(
        effective=SimpleNamespace(sandbox_enabled=True),
        backend=SimpleNamespace(name="windows_default"),
    )


def test_windows_exec_command_uses_direct_powershell_argv(monkeypatch, tmp_path) -> None:
    from opensquilla.tools.builtin import shell

    runtime = _windows_runtime()

    monkeypatch.setattr(
        shell,
        "_trusted_windows_powershell_path",
        lambda: r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
    )

    argv = shell._sandbox_shell_backend_argv("Write-Output ok", runtime, cwd=tmp_path)

    assert argv[0] == r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
    assert "-NoLogo" in argv
    assert "-NoProfile" in argv
    assert "-NonInteractive" in argv
    assert "-ExecutionPolicy" in argv
    assert "Bypass" in argv
    assert "-Command" in argv
    assert "Write-Output ok" in argv
    assert "-c" not in argv[:3]
    assert "python" not in argv[0].lower()


def test_windows_exec_command_unwraps_nested_powershell_command(monkeypatch, tmp_path) -> None:
    from opensquilla.tools.builtin import shell

    runtime = _windows_runtime()

    monkeypatch.setattr(
        shell,
        "_trusted_windows_powershell_path",
        lambda: r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
    )

    argv = shell._sandbox_shell_backend_argv(
        (
            "& 'C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe' "
            '-NoProfile -Command "Write-Output child-ok"'
        ),
        runtime,
        cwd=tmp_path,
    )

    assert argv[0] == r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
    assert argv[-1] == "Write-Output child-ok"

    direct_argv = shell._sandbox_shell_backend_argv(
        'powershell.exe -NoProfile -Command "Write-Output child-ok"',
        runtime,
        cwd=tmp_path,
    )

    assert direct_argv[-1] == "Write-Output child-ok"


@pytest.mark.asyncio
async def test_windows_exec_command_uses_shared_path_envelopes(monkeypatch, tmp_path) -> None:
    from opensquilla.sandbox.config import SandboxSettings
    from opensquilla.sandbox.policy import build_policy
    from opensquilla.sandbox.types import SecurityLevel
    from opensquilla.tools.builtin import shell

    runtime = _windows_runtime()
    policy = build_policy(
        SecurityLevel.STANDARD,
        "shell.exec",
        tmp_path,
        SandboxSettings(
            sandbox=True,
            security_grading=True,
            backend="windows_default",
            network_default="none",
        ),
        trusted=True,
    )
    request = SimpleNamespace(
        cwd=tmp_path,
        action_kind="shell.exec",
        policy=policy,
        reason="",
        session_id="s1",
        run_mode="trusted",
    )

    async def _fake_gate_action(**kwargs):
        return object(), policy, request

    async def _fake_preflight(*args, **kwargs):
        return None

    backend_called = False

    async def _fake_run_backend(request, *, runtime=None):
        nonlocal backend_called
        backend_called = True
        return SimpleNamespace(returncode=0, stdout="ok\n", stderr="", backend_notes=())

    def _blocked_write_envelope(*args, **kwargs):
        return {
            "status": "blocked",
            "reason": "sandbox_path",
            "message": "shared path envelope blocked this command",
        }

    monkeypatch.setattr(shell, "get_runtime", lambda: runtime)
    monkeypatch.setattr(shell, "gate_action", _fake_gate_action)
    monkeypatch.setattr(shell, "preflight_subprocess_managed_network", _fake_preflight)
    monkeypatch.setattr(shell, "_run_backend_with_managed_network", _fake_run_backend)
    monkeypatch.setattr(shell, "_sandbox_write_path_access_envelope", _blocked_write_envelope)
    monkeypatch.setattr(
        shell,
        "check_safe_bin",
        lambda command: SimpleNamespace(allowed=True, needs_approval=False, reason=""),
    )

    token = current_tool_context.set(
        ToolContext(
            is_owner=True,
            caller_kind=CallerKind.CLI,
            workspace_dir=str(tmp_path),
            session_key="s1",
            run_mode="trusted",
        )
    )
    try:
        result = await shell.exec_command('where opensquilla 2>nul || echo "missing"')
    finally:
        current_tool_context.reset(token)

    assert "shared path envelope blocked this command" in result
    assert backend_called is False


@pytest.mark.asyncio
async def test_windows_exec_command_merges_shell_active_mounts(
    monkeypatch,
    tmp_path,
) -> None:
    from opensquilla.sandbox.config import SandboxSettings
    from opensquilla.sandbox.policy import build_policy
    from opensquilla.sandbox.types import SecurityLevel
    from opensquilla.tools.builtin import shell

    runtime = _windows_runtime()
    policy = build_policy(
        SecurityLevel.STANDARD,
        "shell.exec",
        tmp_path,
        SandboxSettings(
            sandbox=True,
            security_grading=True,
            backend="windows_default",
            network_default="none",
        ),
        trusted=True,
    )
    request = SimpleNamespace(
        cwd=tmp_path,
        action_kind="shell.exec",
        policy=policy,
        reason="",
        session_id="s1",
        run_mode="trusted",
    )

    async def _fake_gate_action(**kwargs):
        return object(), policy, request

    async def _fake_preflight(*args, **kwargs):
        return None

    backend_requests = []

    async def _fake_run_backend(request, *, runtime=None):
        backend_requests.append(request)
        return SimpleNamespace(returncode=0, stdout="ok\n", stderr="", backend_notes=())

    mounted = tmp_path / "external"
    mounted.mkdir()

    monkeypatch.setattr(shell, "get_runtime", lambda: runtime)
    monkeypatch.setattr(shell, "gate_action", _fake_gate_action)
    monkeypatch.setattr(shell, "preflight_subprocess_managed_network", _fake_preflight)
    monkeypatch.setattr(shell, "_run_backend_with_managed_network", _fake_run_backend)
    monkeypatch.setattr(
        shell,
        "_active_sandbox_mounts",
        lambda: [{"path": str(mounted), "access": "rw"}],
    )
    monkeypatch.setattr(
        shell,
        "check_safe_bin",
        lambda command: SimpleNamespace(allowed=True, needs_approval=False, reason=""),
    )

    token = current_tool_context.set(
        ToolContext(
            is_owner=True,
            caller_kind=CallerKind.CLI,
            workspace_dir=str(tmp_path),
            session_key="s1",
            run_mode="trusted",
        )
    )
    try:
        result = await shell.exec_command("Write-Output ok")
    finally:
        current_tool_context.reset(token)

    assert "ok" in result
    assert backend_requests
    assert any(mount.host_path == mounted for mount in backend_requests[0].policy.mounts)


@pytest.mark.asyncio
async def test_windows_exec_command_blocks_runtime_readonly_write_target(
    monkeypatch,
    tmp_path,
) -> None:
    from opensquilla.sandbox.config import SandboxSettings
    from opensquilla.sandbox.policy import build_policy
    from opensquilla.sandbox.types import SecurityLevel
    from opensquilla.tools.builtin import shell

    runtime = _windows_runtime()
    policy = build_policy(
        SecurityLevel.STANDARD,
        "shell.exec",
        tmp_path,
        SandboxSettings(
            sandbox=True,
            security_grading=True,
            backend="windows_default",
            network_default="none",
        ),
        trusted=True,
    )
    request = SimpleNamespace(
        cwd=tmp_path,
        action_kind="shell.exec",
        policy=policy,
        reason="",
        session_id="s1",
        run_mode="trusted",
    )
    runtime_root = tmp_path / "runtime-src"
    runtime_root.mkdir()
    target = runtime_root / "__write_should_not_happen__.txt"

    async def _fake_gate_action(**kwargs):
        return object(), policy, request

    async def _fake_preflight(*args, **kwargs):
        return None

    async def _fake_run_backend(request, *, runtime=None):
        return SimpleNamespace(returncode=0, stdout="ok\n", stderr="", backend_notes=())

    monkeypatch.setattr(shell, "get_runtime", lambda: runtime)
    monkeypatch.setattr(shell, "gate_action", _fake_gate_action)
    monkeypatch.setattr(shell, "preflight_subprocess_managed_network", _fake_preflight)
    monkeypatch.setattr(shell, "_run_backend_with_managed_network", _fake_run_backend)
    monkeypatch.setattr(shell, "_windows_runtime_readonly_roots", lambda: (runtime_root,))
    monkeypatch.setattr(
        shell,
        "check_safe_bin",
        lambda command: SimpleNamespace(allowed=True, needs_approval=False, reason=""),
    )

    token = current_tool_context.set(
        ToolContext(
            is_owner=True,
            caller_kind=CallerKind.CLI,
            workspace_dir=str(tmp_path),
            session_key="s1",
            run_mode="trusted",
        )
    )
    try:
        result = await shell.exec_command(f'echo "test" > "{target}"')
    finally:
        current_tool_context.reset(token)

    payload = json.loads(result)
    assert payload["reason"] == "runtime_readonly"
    assert payload["resolved_path"] == str(target)
