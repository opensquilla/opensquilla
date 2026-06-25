from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from opensquilla.tools.types import CallerKind, ToolContext, current_tool_context


def _windows_runtime() -> SimpleNamespace:
    return SimpleNamespace(
        effective=SimpleNamespace(sandbox_enabled=True),
        backend=SimpleNamespace(name="windows_default"),
    )


def test_windows_exec_command_uses_shell_host_wrapper(monkeypatch, tmp_path) -> None:
    from opensquilla.tools.builtin import shell

    runtime = _windows_runtime()

    monkeypatch.setattr(
        shell,
        "_trusted_windows_powershell_path",
        lambda: r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
    )

    argv = shell._sandbox_shell_backend_argv("Write-Output ok", runtime, cwd=tmp_path)

    assert argv[:3] == (
        sys.executable,
        "-c",
        shell._WINDOWS_SANDBOX_SHELL_HOST_CODE,
    )
    assert argv[3] == r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
    assert argv[4] == "Write-Output ok"
    assert argv[5] == str(tmp_path)
    assert argv[6] == str(tmp_path / ".opensquilla-cache" / "shell-host")


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

    assert argv[:3] == (
        sys.executable,
        "-c",
        shell._WINDOWS_SANDBOX_SHELL_HOST_CODE,
    )
    assert argv[3] == r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
    assert argv[4] == "Write-Output child-ok"

    direct_argv = shell._sandbox_shell_backend_argv(
        'powershell.exe -NoProfile -Command "Write-Output child-ok"',
        runtime,
        cwd=tmp_path,
    )

    assert direct_argv[4] == "Write-Output child-ok"


def test_windows_exec_command_prefers_cmd_package_manager_shims(
    monkeypatch,
    tmp_path,
) -> None:
    from opensquilla.tools.builtin import shell

    runtime = _windows_runtime()

    monkeypatch.setattr(
        shell,
        "_trusted_windows_powershell_path",
        lambda: r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
    )

    argv = shell._sandbox_shell_backend_argv("npm view lodash version", runtime, cwd=tmp_path)

    assert argv[4] == "& 'npm.cmd' 'view' 'lodash' 'version'"


@pytest.mark.asyncio
async def test_windows_exec_command_does_not_mount_program_files_tools_per_command(
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
    node_root = tmp_path / "Program Files" / "nodejs"
    git_root = tmp_path / "Program Files" / "Git"
    node_root.mkdir(parents=True)
    (git_root / "cmd").mkdir(parents=True)

    (node_root / "npm.cmd").write_text("@echo off\r\n", encoding="utf-8")
    (git_root / "cmd" / "git.exe").write_text("", encoding="utf-8")

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

    monkeypatch.setattr(shell, "get_runtime", lambda: runtime)
    monkeypatch.setattr(shell, "gate_action", _fake_gate_action)
    monkeypatch.setattr(shell, "preflight_subprocess_managed_network", _fake_preflight)
    monkeypatch.setattr(shell, "_run_backend_with_managed_network", _fake_run_backend)
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
        result = await shell.exec_command(
            (
                "npm view lodash version && "
                "git ls-remote https://github.com/opensquilla/opensquilla.git HEAD"
            ),
            workdir=str(tmp_path),
            env={"PATH": f"{node_root}{os.pathsep}{git_root / 'cmd'}"},
        )
    finally:
        current_tool_context.reset(token)

    assert "ok" in result
    assert backend_requests
    mount_paths = {mount.host_path for mount in backend_requests[0].policy.mounts}
    assert node_root not in mount_paths
    assert git_root not in mount_paths


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


def test_shell_blocks_runtime_python_environment_bootstrap(monkeypatch, tmp_path) -> None:
    from opensquilla.tools.builtin import shell

    runtime_root = tmp_path / "runtime-venv"
    runtime_root.mkdir()

    monkeypatch.setattr(shell, "_runtime_readonly_roots", lambda runtime=None: (runtime_root,))
    monkeypatch.setattr(shell, "full_host_access_active", lambda: False)

    payload = shell._runtime_readonly_shell_block(
        "exec_command",
        "python -m ensurepip --upgrade",
        str(tmp_path),
        runtime=SimpleNamespace(backend=SimpleNamespace(name="bubblewrap")),
    )

    assert payload is not None
    assert payload["reason"] == "runtime_readonly"
    assert payload["runtime_operation"] == "python -m ensurepip"
    assert payload["readonly_root"] == str(runtime_root)


def test_shell_blocks_runtime_python_package_install(monkeypatch, tmp_path) -> None:
    from opensquilla.tools.builtin import shell

    runtime_root = tmp_path / "runtime-venv"
    runtime_python = runtime_root / "bin" / "python"
    runtime_python.parent.mkdir(parents=True)
    runtime_python.write_text("", encoding="utf-8")

    monkeypatch.setattr(shell, "_runtime_readonly_roots", lambda runtime=None: (runtime_root,))
    monkeypatch.setattr(shell, "full_host_access_active", lambda: False)

    payload = shell._runtime_readonly_shell_block(
        "exec_command",
        f"{runtime_python} -m pip install requests",
        str(tmp_path),
        runtime=SimpleNamespace(backend=SimpleNamespace(name="bubblewrap")),
    )

    assert payload is not None
    assert payload["reason"] == "runtime_readonly"
    assert payload["runtime_operation"] == "python -m pip install"


def test_shell_allows_explicit_project_venv_package_install(monkeypatch, tmp_path) -> None:
    from opensquilla.tools.builtin import shell

    runtime_root = tmp_path / "runtime-venv"
    project_python = tmp_path / "project" / ".venv" / "bin" / "python"
    project_python.parent.mkdir(parents=True)
    project_python.write_text("", encoding="utf-8")

    monkeypatch.setattr(shell, "_runtime_readonly_roots", lambda runtime=None: (runtime_root,))
    monkeypatch.setattr(shell, "full_host_access_active", lambda: False)

    payload = shell._runtime_readonly_shell_block(
        "exec_command",
        f"{project_python} -m pip install requests",
        str(tmp_path),
        runtime=SimpleNamespace(backend=SimpleNamespace(name="bubblewrap")),
    )

    assert payload is None


def test_shell_allows_explicit_project_venv_ensurepip(monkeypatch, tmp_path) -> None:
    from opensquilla.tools.builtin import shell

    runtime_root = tmp_path / "runtime-venv"
    project_python = tmp_path / "project" / ".venv" / "bin" / "python"
    project_python.parent.mkdir(parents=True)
    project_python.write_text("", encoding="utf-8")

    monkeypatch.setattr(shell, "_runtime_readonly_roots", lambda runtime=None: (runtime_root,))
    monkeypatch.setattr(shell, "full_host_access_active", lambda: False)

    payload = shell._runtime_readonly_shell_block(
        "exec_command",
        f"{project_python} -m ensurepip --upgrade",
        str(tmp_path),
        runtime=SimpleNamespace(backend=SimpleNamespace(name="bubblewrap")),
    )

    assert payload is None


def test_shell_blocks_windows_runtime_python_environment_bootstrap(monkeypatch) -> None:
    from opensquilla.tools.builtin import shell

    runtime_root = Path(r"X:\workspace\.venv")

    monkeypatch.setattr(shell, "_runtime_readonly_roots", lambda runtime=None: (runtime_root,))
    monkeypatch.setattr(shell, "full_host_access_active", lambda: False)

    payload = shell._runtime_readonly_shell_block(
        "exec_command",
        r"X:\workspace\.venv\Scripts\python.exe -m ensurepip --upgrade",
        r"X:\workspace",
        runtime=SimpleNamespace(backend=SimpleNamespace(name="windows_default")),
    )

    assert payload is not None
    assert payload["reason"] == "runtime_readonly"
    assert payload["runtime_operation"] == "python -m ensurepip"
    assert payload["readonly_root"] == str(runtime_root)


def test_shell_allows_windows_project_venv_ensurepip(monkeypatch) -> None:
    from opensquilla.tools.builtin import shell

    runtime_root = Path(r"X:\workspace\.venv")

    monkeypatch.setattr(shell, "_runtime_readonly_roots", lambda runtime=None: (runtime_root,))
    monkeypatch.setattr(shell, "full_host_access_active", lambda: False)

    payload = shell._runtime_readonly_shell_block(
        "exec_command",
        r"X:\workspace\.tmp\proj\.venv\Scripts\python.exe -m ensurepip --upgrade",
        r"X:\workspace",
        runtime=SimpleNamespace(backend=SimpleNamespace(name="windows_default")),
    )

    assert payload is None


@pytest.mark.asyncio
async def test_windows_exec_command_full_host_access_skips_runtime_readonly_block(
    monkeypatch,
    tmp_path,
) -> None:
    from opensquilla.tools.builtin import shell

    runtime = _windows_runtime()
    runtime_root = tmp_path / "runtime-src"
    runtime_root.mkdir()
    target = runtime_root / "__full_host_should_reach_host__.txt"
    host_calls = []

    async def _fake_run_host_shell_command(*args, **kwargs):
        host_calls.append((args, kwargs))
        return "exit_code=0\nhost-ok\n"

    monkeypatch.setattr(shell, "get_runtime", lambda: runtime)
    monkeypatch.setattr(shell, "_windows_runtime_readonly_roots", lambda: (runtime_root,))
    monkeypatch.setattr(shell, "_run_host_shell_command", _fake_run_host_shell_command)
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
            run_mode="full",
        )
    )
    try:
        result = await shell.exec_command(f'echo "test" > "{target}"')
    finally:
        current_tool_context.reset(token)

    assert "host-ok" in result
    assert host_calls
