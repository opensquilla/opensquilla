from __future__ import annotations

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


@pytest.mark.asyncio
async def test_windows_exec_command_skips_legacy_path_envelopes(monkeypatch, tmp_path) -> None:
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

    async def _fake_run_backend(request, *, runtime=None):
        return SimpleNamespace(returncode=0, stdout="ok\n", stderr="", backend_notes=())

    def _legacy_path_envelope_called(*args, **kwargs):
        raise AssertionError(
            "legacy shell path envelope should not run for windows process sandbox"
        )

    monkeypatch.setattr(shell, "get_runtime", lambda: runtime)
    monkeypatch.setattr(shell, "gate_action", _fake_gate_action)
    monkeypatch.setattr(shell, "preflight_subprocess_managed_network", _fake_preflight)
    monkeypatch.setattr(shell, "_run_backend_with_managed_network", _fake_run_backend)
    monkeypatch.setattr(shell, "_sandbox_workdir_access_envelope", _legacy_path_envelope_called)
    monkeypatch.setattr(shell, "_sandbox_read_path_access_envelope", _legacy_path_envelope_called)
    monkeypatch.setattr(shell, "_sandbox_write_path_access_envelope", _legacy_path_envelope_called)
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

    assert "ok" in result


@pytest.mark.asyncio
async def test_windows_exec_command_does_not_merge_shell_active_mounts(
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

    async def _fake_run_backend(request, *, runtime=None):
        return SimpleNamespace(returncode=0, stdout="ok\n", stderr="", backend_notes=())

    monkeypatch.setattr(shell, "get_runtime", lambda: runtime)
    monkeypatch.setattr(shell, "gate_action", _fake_gate_action)
    monkeypatch.setattr(shell, "preflight_subprocess_managed_network", _fake_preflight)
    monkeypatch.setattr(shell, "_run_backend_with_managed_network", _fake_run_backend)
    monkeypatch.setattr(
        shell,
        "_policy_with_active_tool_mounts",
        lambda policy: (_ for _ in ()).throw(
            AssertionError("legacy active mount merge should not run for windows process sandbox")
        ),
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
