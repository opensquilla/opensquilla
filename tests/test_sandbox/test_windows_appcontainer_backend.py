from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from opensquilla.sandbox.config import SandboxSettings
from opensquilla.sandbox.types import (
    MountSpec,
    NetworkMode,
    NetworkProxySpec,
    ResourceLimits,
    SandboxBackendError,
    SandboxPolicy,
    SandboxRequest,
    SecurityLevel,
)


def _policy(
    workspace: Path,
    *,
    network: NetworkMode = NetworkMode.NONE,
    network_proxy: NetworkProxySpec | None = None,
    wall_timeout_s: float = 5.0,
) -> SandboxPolicy:
    return SandboxPolicy(
        level=SecurityLevel.STANDARD,
        network=network,
        network_proxy=network_proxy,
        mounts=(
            MountSpec(
                host_path=workspace,
                sandbox_path=Path("/workspace"),
                mode="rw",
                required=True,
            ),
        ),
        workspace_rw=True,
        tmp_writable=True,
        limits=ResourceLimits(wall_timeout_s=wall_timeout_s),
        env_allowlist=("PATH", "LANG"),
        require_approval=False,
    )


def _request(tmp_path: Path, policy: SandboxPolicy | None = None) -> SandboxRequest:
    return SandboxRequest(
        argv=("cmd", "/c", "echo", "ok"),
        cwd=tmp_path,
        action_kind="shell.exec",
        policy=policy or _policy(tmp_path),
        env={"PATH": r"C:\Windows\System32", "SECRET": "not-forwarded"},
    )


def test_config_accepts_windows_appcontainer_backend() -> None:
    settings = SandboxSettings(sandbox=True, backend="windows_appcontainer")

    assert settings.backend == "windows_appcontainer"


@pytest.mark.asyncio
async def test_managed_proxy_env_has_case_unique_keys_for_windows_backend(
    tmp_path: Path,
) -> None:
    from types import SimpleNamespace

    from opensquilla.sandbox import integration as integration_mod

    policy = _policy(
        tmp_path,
        network=NetworkMode.PROXY_ALLOWLIST,
        network_proxy=NetworkProxySpec(host="127.0.0.1", port=18080),
    )
    request = _request(tmp_path, policy)
    request.env.update(
        {
            "HTTP_PROXY": "http://attacker.invalid:1",
            "http_proxy": "http://attacker.invalid:2",
            "HTTPS_PROXY": "http://attacker.invalid:3",
            "https_proxy": "http://attacker.invalid:4",
            "NO_PROXY": "*",
            "no_proxy": "*",
        }
    )
    runtime = SimpleNamespace(
        backend=SimpleNamespace(name="windows_appcontainer"),
    )

    managed = await integration_mod.prepare_subprocess_managed_network_proxy(
        request,
        runtime=runtime,
    )

    keys_upper = [key.upper() for key in managed.request.env]
    assert len(keys_upper) == len(set(keys_upper))
    assert managed.request.env["HTTP_PROXY"] == "http://127.0.0.1:18080"
    assert managed.request.env["HTTPS_PROXY"] == "http://127.0.0.1:18080"
    assert managed.request.env["NO_PROXY"] == ""
    assert "http_proxy" not in managed.request.env
    assert "https_proxy" not in managed.request.env
    assert "no_proxy" not in managed.request.env


def test_appcontainer_profile_name_normalizes_session_id() -> None:
    from opensquilla.sandbox.backend.windows_primitives import appcontainer_profile_name

    assert (
        appcontainer_profile_name("agent:main:webchat:abc")
        == "opensquilla-sandbox-agent-main-webchat-abc"
    )
    assert (
        appcontainer_profile_name("agent/main webchat:abc!")
        == "opensquilla-sandbox-agent-main-webchat-abc"
    )


def test_appcontainer_profile_name_defaults_and_caps_length() -> None:
    from opensquilla.sandbox.backend.windows_primitives import appcontainer_profile_name

    assert appcontainer_profile_name(" ! ") == "opensquilla-sandbox-default"

    profile_name = appcontainer_profile_name("AGENT:" + ("very-long-session-" * 8))

    assert profile_name.startswith("opensquilla-sandbox-agent-very-long")
    assert profile_name == profile_name.lower()
    assert len(profile_name) <= 64


def test_windows_backend_shell_argv_uses_python_host_with_pinned_powershell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.tools.builtin import shell

    class Runtime:
        backend = type("Backend", (), {"name": "windows_appcontainer"})()

    command = r'Remove-Item -Path "D:\opensquilla\temp.txt"'
    monkeypatch.setenv("SystemRoot", r"C:\Windows")

    argv = shell._sandbox_shell_backend_argv(command, Runtime())

    assert argv[0] == sys.executable
    assert argv[1] == "-c"
    assert "subprocess.run" in argv[2]
    assert argv[3] == r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
    assert argv[4] == command


def test_windows_backend_shell_argv_ignores_untrusted_comspec_for_shell_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.tools.builtin import shell

    class Runtime:
        backend = type("Backend", (), {"name": "windows_appcontainer"})()

    monkeypatch.setenv("COMSPEC", "cmd.exe")
    monkeypatch.setenv("SystemRoot", r"D:\Windows")

    argv = shell._sandbox_shell_backend_argv("echo ok", Runtime())

    assert argv[0] == sys.executable
    assert argv[3] == r"D:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
    assert argv[4] == "echo ok"


def test_windows_backend_maps_posix_tmp_to_session_temp_root(
    tmp_path: Path,
) -> None:
    from opensquilla.tools.builtin import shell
    from opensquilla.tools.types import ToolContext, current_tool_context

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    token = current_tool_context.set(
        ToolContext(
            workspace_dir=str(workspace),
            session_key="agent:main:webchat:abc",
        )
    )
    try:
        command = shell._windows_translate_posix_tmp_references(
            "python -m venv /tmp/opensquilla-deps-smoke/python-alt",
        )
    finally:
        current_tool_context.reset(token)

    expected = (
        workspace
        / ".opensquilla"
        / "tmp"
        / "agent-main-webchat-abc"
        / "opensquilla-deps-smoke"
        / "python-alt"
    )
    assert str(expected) in command
    assert "/tmp/" not in command
    assert expected.parent.exists()


@pytest.mark.skipif(not sys.platform.startswith("win"), reason="Windows command shim test")
def test_windows_shell_host_uses_in_memory_python_functions_without_cmd_shims(
    tmp_path: Path,
) -> None:
    from opensquilla.tools.builtin import shell

    fake_powershell = tmp_path / "fake-powershell.cmd"
    captured = tmp_path / "captured.txt"
    fake_powershell.write_text(
        "@echo off\r\n"
        f'echo %* > "{captured}"\r\n',
        encoding="utf-8",
    )
    env = {
        "COMSPEC": r"C:\Windows\System32\cmd.exe",
        "PATH": r"C:\Windows\System32",
        "PATHEXT": ".COM;.EXE;.BAT;.CMD",
        "SystemRoot": r"C:\Windows",
        "TEMP": str(tmp_path),
        "TMP": str(tmp_path),
    }

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            shell._WINDOWS_SANDBOX_SHELL_HOST_CODE,
            str(fake_powershell),
            "Get-Command python",
        ],
        cwd=str(tmp_path),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    shim_root = tmp_path / "opensquilla-python-shims"
    assert not shim_root.exists()
    captured_args = captured.read_text(encoding="utf-8")
    assert "Set-Alias -Name python " in captured_args
    assert "Set-Alias -Name python3 " in captured_args
    assert "Set-Alias -Name py " in captured_args
    assert os.path.basename(sys.executable).lower() in captured_args.lower()


@pytest.mark.asyncio
async def test_windows_proxy_allowlist_missing_fails_preflight_before_backend(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from opensquilla.sandbox import integration as integration_mod
    from opensquilla.sandbox.run_context import PackageBundleGrant, RunContext
    from opensquilla.sandbox.run_mode import RunMode
    from opensquilla.tools.types import ToolContext, current_tool_context

    policy = _policy(tmp_path, network=NetworkMode.PROXY_ALLOWLIST)
    request = SandboxRequest(
        argv=("powershell", "-Command", "python -m pip install humanize"),
        cwd=tmp_path,
        action_kind="shell.exec",
        policy=policy,
        env={"PATH": r"C:\Windows\System32"},
    )

    class _Ledger:
        async def record_denial(self, *args: object, **kwargs: object) -> None:
            return None

    runtime = SimpleNamespace(
        backend=SimpleNamespace(name="windows_appcontainer"),
        workspace=tmp_path,
        ledger=_Ledger(),
    )
    monkeypatch.setattr(
        integration_mod,
        "_windows_proxy_allowlist_enforced",
        lambda runtime: False,
        raising=False,
    )

    token = current_tool_context.set(
        ToolContext(
            is_owner=True,
            workspace_dir=str(tmp_path),
            session_key="s1",
            run_mode="trusted",
            sandbox_run_context=RunContext(
                run_mode=RunMode.TRUSTED,
                workspace=str(tmp_path),
                bundles=(PackageBundleGrant(bundle_id="python-package-install"),),
            ),
        )
    )
    try:
        result = await integration_mod.preflight_subprocess_managed_network(
            request,
            runtime,
        )
    finally:
        current_tool_context.reset(token)

    assert result is not None
    assert not isinstance(result, dict)
    message = result.message
    assert "Windows sandbox managed network" in message
    assert "PROXY_ALLOWLIST" in message
    assert "http_request" in message
    assert result.retryable is False


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("New-Item -ItemType Directory -Path /tmp/proj", "/tmp/proj"),
        ("mkdir /tmp/proj", "/tmp/proj"),
        ("python -m venv /tmp/proj/.venv", "/tmp/proj/.venv"),
        ("uv venv /tmp/proj/.venv", "/tmp/proj/.venv"),
        ("Remove-Item -LiteralPath /tmp/proj/out.txt -Force", "/tmp/proj/out.txt"),
        ("echo hello > /tmp/proj/out.txt", "/tmp/proj/out.txt"),
        ('cmd /c "mkdir /tmp/proj"', "/tmp/proj"),
        ('powershell -Command "New-Item -ItemType Directory -Path /tmp/proj"', "/tmp/proj"),
    ],
)
def test_windows_shell_write_targets_cover_windows_commands(
    command: str,
    expected: str,
) -> None:
    from opensquilla.tools.builtin import shell

    assert expected in shell._windows_shell_write_targets(command)


@pytest.mark.asyncio
async def test_execute_code_windows_sandbox_rejects_environment_subprocess_misuse(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from opensquilla.tools.builtin import code_exec

    runtime = SimpleNamespace(
        effective=SimpleNamespace(sandbox_enabled=True),
        backend=SimpleNamespace(name="windows_appcontainer"),
        workspace=tmp_path,
    )

    async def fail_gate_action(*args: object, **kwargs: object) -> object:
        raise AssertionError("execute_code should reject before sandbox gate_action")

    monkeypatch.setattr(code_exec, "get_runtime", lambda: runtime)
    monkeypatch.setattr(code_exec, "gate_action", fail_gate_action)

    payload = json.loads(
        await code_exec.execute_code(
            "import subprocess\n"
            "subprocess.run(['python', '-m', 'venv', '/tmp/opensquilla-deps-smoke'])"
        )
    )

    assert payload["status"] == "unsupported_tool_use"
    assert payload["tool"] == "execute_code"
    assert payload["recommended_tool"] == "exec_command"
    assert "venv" in payload["message"]


def test_non_windows_backend_shell_argv_uses_posix_shell() -> None:
    from opensquilla.tools.builtin import shell

    class Runtime:
        backend = type("Backend", (), {"name": "bubblewrap"})()

    argv = shell._sandbox_shell_backend_argv("echo ok", Runtime())

    assert argv == ("sh", "-lc", "echo ok")


@pytest.mark.asyncio
async def test_exec_command_windows_backend_uses_pinned_powershell_argv(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from types import SimpleNamespace

    from opensquilla.tools.builtin import shell

    policy = _policy(tmp_path)
    runtime = SimpleNamespace(
        effective=SimpleNamespace(sandbox_enabled=True),
        backend=SimpleNamespace(name="windows_appcontainer"),
        workspace=tmp_path,
    )
    gate_request = SimpleNamespace(
        cwd=tmp_path,
        action_kind="shell.exec",
        policy=policy,
        reason="",
    )
    captured: dict[str, object] = {}

    async def fake_gate_action(**kwargs: object) -> tuple[object, SandboxPolicy, object]:
        captured["gate"] = kwargs
        return object(), policy, gate_request

    async def fake_run_under_backend(request: SandboxRequest, *, runtime: object) -> object:
        captured["request"] = request
        return SimpleNamespace(returncode=0, stdout="ok\n", stderr="", backend_notes=())

    async def fake_preflight(request: SandboxRequest, runtime: object) -> object | None:
        return None

    monkeypatch.setenv("SystemRoot", r"C:\Windows")
    monkeypatch.setattr(shell, "get_runtime", lambda: runtime)
    monkeypatch.setattr(shell, "_host_execution_allowed", lambda: False)
    monkeypatch.setattr(
        shell,
        "check_safe_bin",
        lambda command: SimpleNamespace(allowed=True, needs_approval=False, reason=""),
    )
    monkeypatch.setattr(shell, "gate_action", fake_gate_action)
    monkeypatch.setattr(shell, "preflight_subprocess_managed_network", fake_preflight)
    monkeypatch.setattr(shell, "run_under_backend", fake_run_under_backend)

    await shell.exec_command("echo ok", workdir=str(tmp_path))

    request = captured["request"]
    assert isinstance(request, SandboxRequest)
    assert request.argv[0] == sys.executable
    assert request.argv[1] == "-c"
    assert request.argv[3] == r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
    assert request.argv[4] == "echo ok"


@pytest.mark.asyncio
async def test_exec_command_windows_backend_translates_tmp_and_sets_session_temp_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from opensquilla.tools.builtin import shell
    from opensquilla.tools.types import ToolContext, current_tool_context

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    policy = _policy(workspace)
    runtime = SimpleNamespace(
        effective=SimpleNamespace(sandbox_enabled=True),
        backend=SimpleNamespace(name="windows_appcontainer"),
        workspace=workspace,
    )
    gate_request = SimpleNamespace(
        cwd=workspace,
        action_kind="shell.exec",
        policy=policy,
        reason="",
    )
    captured: dict[str, object] = {}

    async def fake_gate_action(**kwargs: object) -> tuple[object, SandboxPolicy, object]:
        captured["gate"] = kwargs
        return object(), policy, gate_request

    async def fake_run_under_backend(request: SandboxRequest, *, runtime: object) -> object:
        captured["request"] = request
        return SimpleNamespace(returncode=0, stdout="ok\n", stderr="", backend_notes=())

    async def fake_preflight(request: SandboxRequest, runtime: object) -> object | None:
        return None

    monkeypatch.setenv("SystemRoot", r"C:\Windows")
    monkeypatch.setattr(shell, "get_runtime", lambda: runtime)
    monkeypatch.setattr(shell, "_host_execution_allowed", lambda: False)
    monkeypatch.setattr(
        shell,
        "check_safe_bin",
        lambda command: SimpleNamespace(allowed=True, needs_approval=False, reason=""),
    )
    monkeypatch.setattr(shell, "gate_action", fake_gate_action)
    monkeypatch.setattr(shell, "preflight_subprocess_managed_network", fake_preflight)
    monkeypatch.setattr(shell, "run_under_backend", fake_run_under_backend)
    token = current_tool_context.set(
        ToolContext(
            workspace_dir=str(workspace),
            session_key="agent:main:webchat:abc",
        )
    )
    try:
        await shell.exec_command(
            "python -m venv /tmp/opensquilla-deps-smoke/python-alt",
            workdir=str(workspace),
        )
    finally:
        current_tool_context.reset(token)

    expected = (
        workspace
        / ".opensquilla"
        / "tmp"
        / "agent-main-webchat-abc"
        / "opensquilla-deps-smoke"
        / "python-alt"
    )
    request = captured["request"]
    assert isinstance(request, SandboxRequest)
    assert str(expected) in request.argv[4]
    assert "/tmp/" not in request.argv[4]
    assert request.env["TEMP"] == str(expected.parent.parent)
    assert request.env["TMP"] == request.env["TEMP"]
    assert request.env["TMPDIR"] == request.env["TEMP"]
    assert expected.parent.exists()


@pytest.mark.asyncio
async def test_exec_command_windows_python_install_queues_bundle_before_backend(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from opensquilla.gateway.approval_queue import get_approval_queue, reset_approval_queue
    from opensquilla.sandbox import integration as integration_mod
    from opensquilla.sandbox.run_context import RunContext
    from opensquilla.sandbox.run_mode import RunMode
    from opensquilla.tools.builtin import shell
    from opensquilla.tools.types import CallerKind, ToolContext, current_tool_context

    reset_approval_queue()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    venv_python = workspace / ".venv" / "Scripts" / "python.exe"
    policy = _policy(workspace, network=NetworkMode.PROXY_ALLOWLIST)
    runtime = SimpleNamespace(
        effective=SimpleNamespace(sandbox_enabled=True),
        backend=SimpleNamespace(name="windows_appcontainer"),
        workspace=workspace,
    )
    gate_request = SimpleNamespace(
        cwd=workspace,
        action_kind="shell.exec",
        policy=policy,
        reason="",
    )

    async def fake_gate_action(**kwargs: object) -> tuple[object, SandboxPolicy, object]:
        return object(), policy, gate_request

    async def fail_run_under_backend(request: SandboxRequest, *, runtime: object) -> object:
        raise AssertionError("package bundle approval should run before backend execution")

    monkeypatch.setenv("SystemRoot", r"C:\Windows")
    monkeypatch.setattr(
        integration_mod,
        "_windows_proxy_allowlist_enforced",
        lambda runtime: True,
    )
    monkeypatch.setattr(shell, "get_runtime", lambda: runtime)
    monkeypatch.setattr(shell, "_host_execution_allowed", lambda: False)
    monkeypatch.setattr(
        shell,
        "check_safe_bin",
        lambda command: SimpleNamespace(allowed=True, needs_approval=False, reason=""),
    )
    monkeypatch.setattr(shell, "gate_action", fake_gate_action)
    monkeypatch.setattr(shell, "run_under_backend", fail_run_under_backend)
    token = current_tool_context.set(
        ToolContext(
            is_owner=True,
            caller_kind=CallerKind.CLI,
            workspace_dir=str(workspace),
            session_key="s1",
            run_mode="standard",
            sandbox_run_context=RunContext(
                run_mode=RunMode.STANDARD,
                workspace=str(workspace),
            ),
        )
    )
    try:
        payload = json.loads(
            await shell.exec_command(
                f'& "{venv_python}" -m pip install --no-cache-dir httpx[http2] pendulum',
                workdir=str(workspace),
            )
        )
    finally:
        current_tool_context.reset(token)

    assert payload["status"] == "approval_required"
    assert payload["approvalKind"] == "sandbox_network"
    assert payload["bundle_id"] == "python-package-install"
    pending = get_approval_queue().list_pending("exec")
    assert len(pending) == 1
    assert pending[0]["params"]["bundle_id"] == "python-package-install"
    reset_approval_queue()


@pytest.mark.asyncio
async def test_background_process_windows_backend_uses_pinned_powershell_argv(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from types import SimpleNamespace

    from opensquilla.tools.builtin import shell

    class FakeStream:
        async def read(self, size: int) -> bytes:
            return b""

    class FakeProcess:
        stdout = FakeStream()
        stdin = None
        returncode = 0

        async def wait(self) -> int:
            return 0

    class ManagedNetwork:
        def __init__(self, request: SandboxRequest) -> None:
            self.request = request

        async def cleanup(self) -> None:
            return None

    policy = _policy(tmp_path)
    runtime = SimpleNamespace(
        effective=SimpleNamespace(sandbox_enabled=True),
        backend=SimpleNamespace(name="windows_appcontainer"),
        workspace=tmp_path,
    )
    gate_request = SimpleNamespace(
        cwd=tmp_path,
        action_kind="shell.background",
        policy=policy,
        reason="",
    )
    captured: dict[str, object] = {}

    async def fake_gate_action(**kwargs: object) -> tuple[object, SandboxPolicy, object]:
        captured["gate"] = kwargs
        return object(), policy, gate_request

    async def fake_prepare(
        request: SandboxRequest,
        *,
        runtime: object,
    ) -> ManagedNetwork:
        captured["prepared_request"] = request
        return ManagedNetwork(request)

    async def fake_spawn(*, runtime: object, request: SandboxRequest) -> object:
        captured["request"] = request
        return shell._SpawnedBackgroundProcess(process=FakeProcess())  # type: ignore[arg-type]

    async def fake_preflight(request: SandboxRequest, runtime: object) -> object | None:
        return None

    monkeypatch.setenv("SystemRoot", r"C:\Windows")
    monkeypatch.setattr(shell, "get_runtime", lambda: runtime)
    monkeypatch.setattr(shell, "_host_execution_allowed", lambda: False)
    monkeypatch.setattr(
        shell,
        "check_safe_bin",
        lambda command: SimpleNamespace(allowed=True, needs_approval=False, reason=""),
    )
    monkeypatch.setattr(shell, "gate_action", fake_gate_action)
    monkeypatch.setattr(shell, "preflight_subprocess_managed_network", fake_preflight)
    monkeypatch.setattr(shell, "prepare_subprocess_managed_network_proxy", fake_prepare)
    monkeypatch.setattr(shell, "_spawn_sandboxed_background_process", fake_spawn)

    result = await shell.background_process("echo ok", workdir=str(tmp_path), timeout=5)
    session_id = result.splitlines()[0].split("=", 1)[1]
    session = shell._bg_sessions[session_id]
    assert session.collector_task is not None
    await session.collector_task
    shell._bg_sessions.pop(session_id, None)

    request = captured["request"]
    assert isinstance(request, SandboxRequest)
    assert request.argv[0] == sys.executable
    assert request.argv[1] == "-c"
    assert request.argv[3] == r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
    assert request.argv[4] == "echo ok"


def test_windows_command_line_quotes_argv() -> None:
    from opensquilla.sandbox.backend.windows_primitives import _windows_command_line

    assert _windows_command_line(("tool.exe", "plain", "two words")) == (
        'tool.exe plain "two words"'
    )


def test_windows_environment_block_is_double_nul_terminated() -> None:
    from opensquilla.sandbox.backend.windows_primitives import _windows_environment_block

    assert _windows_environment_block({"B": "two", "a": "one"}) == "a=one\0B=two\0\0"


def test_windows_appcontainer_smoke_env_preserves_powershell_module_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.sandbox.backend.windows_primitives import _smoke_env

    monkeypatch.setenv("PSModulePath", r"C:\Windows\System32\WindowsPowerShell\v1.0\Modules")

    env = _smoke_env(r"C:\Windows\System32\cmd.exe")

    folded = {key.casefold(): value for key, value in env.items()}
    assert folded["psmodulepath"] == r"C:\Windows\System32\WindowsPowerShell\v1.0\Modules"


def test_ensure_appcontainer_profile_creates_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.sandbox.backend import windows_primitives as primitives

    class FakeApi:
        def __init__(self) -> None:
            self.created: list[str] = []

        def create_appcontainer_profile(self, profile_name: str) -> int:
            self.created.append(profile_name)
            return 123

        def sid_to_string_and_free(self, sid: int) -> str:
            assert sid == 123
            return "S-1-15-2-123"

    api = FakeApi()

    monkeypatch.setattr(primitives.sys, "platform", "win32")
    monkeypatch.setattr(primitives, "_get_win32_api", lambda: api)

    assert primitives.ensure_appcontainer_profile("opensquilla-sandbox-test") == (
        "S-1-15-2-123"
    )
    assert api.created == ["opensquilla-sandbox-test"]


def test_ensure_appcontainer_profile_derives_existing_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.sandbox.backend import windows_primitives as primitives

    class FakeApi:
        def create_appcontainer_profile(self, profile_name: str) -> int:
            raise primitives._Win32Error("CreateAppContainerProfile", 0x800700B7)

        def derive_appcontainer_sid(self, profile_name: str) -> int:
            assert profile_name == "opensquilla-sandbox-test"
            return 456

        def sid_to_string_and_free(self, sid: int) -> str:
            assert sid == 456
            return "S-1-15-2-456"

    monkeypatch.setattr(primitives.sys, "platform", "win32")
    monkeypatch.setattr(primitives, "_get_win32_api", lambda: FakeApi())

    assert primitives.ensure_appcontainer_profile("opensquilla-sandbox-test") == (
        "S-1-15-2-456"
    )


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"profile_name": "bad\0profile"}, "profile name"),
        ({"argv": ("cmd", "bad\0arg")}, "argv"),
        ({"env": {"BAD\0KEY": "value"}}, "env"),
        ({"env": {"BAD=KEY": "value"}}, "env"),
        ({"env": {"": "value"}}, "env"),
        ({"env": {"Path": "one", "PATH": "two"}}, "env"),
        ({"env": {"KEY": "bad\0value"}}, "env"),
    ],
)
def test_launch_appcontainer_process_rejects_windows_string_hazards(
    kwargs: dict[str, object],
    match: str,
    tmp_path: Path,
) -> None:
    from opensquilla.sandbox.backend import windows_primitives as primitives

    request: dict[str, object] = {
        "profile_name": "opensquilla-sandbox-test",
        "argv": ("cmd", "/c", "echo", "ok"),
        "cwd": tmp_path,
        "env": {"PATH": r"C:\Windows\System32"},
        "timeout": 1.0,
    }
    request.update(kwargs)

    with pytest.raises(SandboxBackendError, match=match):
        primitives._validate_appcontainer_launch_request(**request)


def test_acquire_appcontainer_sid_frees_sid_when_string_conversion_fails() -> None:
    from opensquilla.sandbox.backend import windows_primitives as primitives

    class FakeApi:
        def __init__(self) -> None:
            self.freed: list[int] = []

        def create_appcontainer_profile(self, profile_name: str) -> int:
            assert profile_name == "opensquilla-sandbox-test"
            return 100

        def sid_to_string(self, sid: int) -> str:
            assert sid == 100
            raise primitives._Win32Error("ConvertSidToStringSidW", 5)

        def free_sid(self, sid: int) -> None:
            self.freed.append(sid)

    api = FakeApi()

    with pytest.raises(SandboxBackendError, match="ConvertSidToStringSidW"):
        primitives._acquire_appcontainer_sid(api, "opensquilla-sandbox-test")

    assert api.freed == [100]


def test_native_sync_launch_uses_handle_list_and_job_object(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from opensquilla.sandbox.backend import windows_primitives as primitives

    class FakeApi:
        def __init__(self) -> None:
            self.security_capabilities = None
            self.handle_list = None
            self.ui_acl_grants: list[str] = []
            self.creation_flags = None
            self.created_job = False
            self.kill_on_close_job = None
            self.assigned_job = None
            self.resumed_thread = None
            self.job_finished = False
            self.closed: list[int] = []

        def create_appcontainer_profile(self, profile_name: str) -> int:
            assert profile_name == "opensquilla-sandbox-test"
            return 100

        def sid_to_string(self, sid: int) -> str:
            assert sid == 100
            return "S-1-15-2-100"

        def free_sid(self, sid: int) -> None:
            assert sid == 100

        def grant_current_window_station_and_desktop(self, sid_string: str) -> None:
            self.ui_acl_grants.append(sid_string)

        def create_pipe(
            self,
            *,
            inherit_read: bool = False,
            inherit_write: bool = False,
        ) -> tuple[int, int]:
            if inherit_write:
                return 10, 11
            if inherit_read:
                return 12, 13
            return 14, 15

        def create_appcontainer_attribute_list(
            self,
            security_capabilities: object,
            inherited_handles: tuple[int, ...],
        ) -> str:
            self.security_capabilities = security_capabilities
            self.handle_list = inherited_handles
            return "attributes"

        def create_kill_on_close_job(self) -> int:
            self.created_job = True
            return 200

        def create_process(self, **kwargs: object) -> None:
            self.creation_flags = kwargs["creation_flags"]
            process_info = kwargs["process_info"]
            process_info.hProcess = 300
            process_info.hThread = 301

        def assign_process_to_job(self, job: int, process: int) -> None:
            self.assigned_job = (job, process)

        def resume_thread(self, thread: int) -> None:
            self.resumed_thread = thread

        def close_handle(self, handle: int) -> None:
            if handle == 200:
                self.job_finished = True
            self.closed.append(handle)

        def terminate_job(self, job: int, returncode: int) -> None:
            assert job == 200
            assert returncode == 0
            self.job_finished = True

        def read_file(self, handle: int) -> bytes:
            assert self.job_finished is True
            return b""

        def wait_for_single_object(self, handle: int, timeout: float | None) -> int:
            assert handle == 300
            assert timeout == 1.0
            return primitives._WAIT_OBJECT_0

        def get_exit_code_process(self, handle: int) -> int:
            assert handle == 300
            return 0

        def delete_proc_thread_attribute_list(self, attribute_list: str) -> None:
            assert attribute_list == "attributes"

    api = FakeApi()

    class FakeThread:
        def __init__(
            self,
            *,
            target: object,
            args: tuple[object, ...],
            daemon: bool,
        ) -> None:
            assert daemon is True
            self.target = target
            self.args = args

        def start(self) -> None:
            return None

        def join(self) -> None:
            self.target(*self.args)

    monkeypatch.setattr(primitives, "_get_win32_api", lambda: api)
    monkeypatch.setattr(primitives.threading, "Thread", FakeThread)

    result = primitives._launch_appcontainer_process_native_sync(
        profile_name="opensquilla-sandbox-test",
        argv=("cmd", "/c", "echo", "ok"),
        cwd=tmp_path,
        env={},
        timeout=1.0,
    )

    assert result.returncode == 0
    assert api.ui_acl_grants == ["S-1-15-2-100"]
    assert api.handle_list == (12, 11, 11)
    assert api.creation_flags & primitives._CREATE_SUSPENDED
    assert api.created_job is True
    assert api.assigned_job == (200, 300)
    assert api.resumed_thread == 301
    assert 200 in api.closed


@pytest.mark.asyncio
async def test_launch_appcontainer_process_requires_native_windows(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from opensquilla.sandbox.backend import windows_primitives as primitives

    async def forbidden_subprocess(*args: object, **kwargs: object) -> object:
        raise AssertionError("must not fall back to unsandboxed subprocess execution")

    monkeypatch.setattr(primitives.sys, "platform", "linux")
    monkeypatch.setattr(
        primitives.asyncio,
        "create_subprocess_exec",
        forbidden_subprocess,
    )

    with pytest.raises(SandboxBackendError, match="requires native Windows"):
        await primitives.launch_appcontainer_process(
            profile_name="opensquilla-sandbox-test",
            argv=("cmd", "/c", "echo", "ok"),
            cwd=tmp_path,
            env={},
            timeout=1.0,
        )


@pytest.mark.asyncio
async def test_launch_appcontainer_process_windows_delegates_to_native_without_subprocess(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from opensquilla.sandbox.backend import windows_primitives as primitives
    from opensquilla.sandbox.backend.windows_primitives import AppContainerLaunchResult

    async def forbidden_subprocess(*args: object, **kwargs: object) -> object:
        raise AssertionError("must not fall back to unsandboxed subprocess execution")

    captured: dict[str, object] = {}

    async def fake_native(**kwargs: object) -> AppContainerLaunchResult:
        captured.update(kwargs)
        return AppContainerLaunchResult(returncode=7, stdout=b"out", stderr=b"err")

    monkeypatch.setattr(primitives.sys, "platform", "win32")
    monkeypatch.setattr(
        primitives.asyncio,
        "create_subprocess_exec",
        forbidden_subprocess,
    )
    monkeypatch.setattr(primitives, "_launch_appcontainer_process_native", fake_native)

    result = await primitives.launch_appcontainer_process(
        profile_name="opensquilla-sandbox-test",
        argv=("cmd", "/c", "echo", "ok"),
        cwd=tmp_path,
        env={"PATH": r"C:\Windows\System32"},
        timeout=1.0,
    )

    assert result == AppContainerLaunchResult(returncode=7, stdout=b"out", stderr=b"err")
    assert captured == {
        "profile_name": "opensquilla-sandbox-test",
        "argv": ("cmd", "/c", "echo", "ok"),
        "cwd": tmp_path,
        "env": {"PATH": r"C:\Windows\System32"},
        "timeout": 1.0,
    }


def test_windows_appcontainer_available_requires_enforced_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.sandbox.backend import windows_support as support_mod
    from opensquilla.sandbox.backend.windows_appcontainer import (
        WindowsAppContainerBackend,
    )

    monkeypatch.setattr(support_mod.sys, "platform", "win32")
    monkeypatch.setattr(support_mod, "_ctypes_available", lambda: True)
    monkeypatch.setattr(support_mod, "_appcontainer_smoke_ok", lambda: False)
    monkeypatch.setattr(support_mod, "_restricted_token_smoke_ok", lambda: False)
    monkeypatch.setattr(support_mod, "_wfp_smoke_ok", lambda: False)
    monkeypatch.setattr(support_mod, "_broker_smoke_ok", lambda: False)

    assert WindowsAppContainerBackend().available() is False

    monkeypatch.setattr(support_mod, "_appcontainer_smoke_ok", lambda: True)
    monkeypatch.setattr(support_mod, "_wfp_smoke_ok", lambda: False)
    monkeypatch.setattr(support_mod, "_broker_smoke_ok", lambda: True)
    assert WindowsAppContainerBackend().available() is True

    monkeypatch.setattr(support_mod, "_wfp_smoke_ok", lambda: True)
    assert WindowsAppContainerBackend().available() is True


def test_windows_auto_prefers_appcontainer_when_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.sandbox import backend as backend_mod
    from opensquilla.sandbox.backend.windows_appcontainer import (
        WindowsAppContainerBackend,
    )
    from opensquilla.sandbox.backend.windows_restricted_token import (
        WindowsRestrictedTokenBackend,
    )

    monkeypatch.setattr(backend_mod.sys, "platform", "win32")
    monkeypatch.setattr(WindowsAppContainerBackend, "available", lambda self: True)
    monkeypatch.setattr(WindowsRestrictedTokenBackend, "available", lambda self: True)

    backend = backend_mod.select_backend(SandboxSettings(sandbox=True, backend="auto"))

    assert isinstance(backend, WindowsAppContainerBackend)
    assert backend.name == "windows_appcontainer"


def test_windows_auto_falls_back_to_restricted_token_when_appcontainer_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.sandbox import backend as backend_mod
    from opensquilla.sandbox.backend.windows_appcontainer import (
        WindowsAppContainerBackend,
    )
    from opensquilla.sandbox.backend.windows_restricted_token import (
        WindowsRestrictedTokenBackend,
    )

    monkeypatch.setattr(backend_mod.sys, "platform", "win32")
    monkeypatch.setattr(WindowsAppContainerBackend, "available", lambda self: False)
    monkeypatch.setattr(WindowsRestrictedTokenBackend, "available", lambda self: True)

    backend = backend_mod.select_backend(SandboxSettings(sandbox=True, backend="auto"))

    assert isinstance(backend, WindowsRestrictedTokenBackend)
    assert backend.name == "windows_restricted_token"


def test_explicit_windows_appcontainer_selects_backend_when_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.sandbox import backend as backend_mod
    from opensquilla.sandbox.backend.windows_appcontainer import (
        WindowsAppContainerBackend,
    )

    monkeypatch.setattr(WindowsAppContainerBackend, "available", lambda self: True)

    backend = backend_mod.select_backend(
        SandboxSettings(sandbox=True, backend="windows_appcontainer")
    )

    assert isinstance(backend, WindowsAppContainerBackend)


def test_explicit_windows_appcontainer_fails_closed_when_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.sandbox import backend as backend_mod
    from opensquilla.sandbox.backend.windows_appcontainer import (
        WindowsAppContainerBackend,
    )

    monkeypatch.setattr(WindowsAppContainerBackend, "available", lambda self: False)

    with pytest.raises(
        SandboxBackendError,
        match="sandbox backend 'windows_appcontainer' is unavailable",
    ):
        backend_mod.select_backend(
            SandboxSettings(sandbox=True, backend="windows_appcontainer")
        )


@pytest.mark.asyncio
async def test_run_invokes_helper_and_serializes_policy_summary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from opensquilla.sandbox.backend import windows_appcontainer as win_mod
    from opensquilla.sandbox.backend.windows_appcontainer import (
        WindowsAppContainerBackend,
    )

    policy = _policy(
        tmp_path,
        network=NetworkMode.PROXY_ALLOWLIST,
        network_proxy=NetworkProxySpec(host="127.0.0.1", port=18080),
    )

    class FakeProcess:
        returncode = 9

        async def communicate(self, input: bytes | None = None) -> tuple[bytes, bytes]:
            assert input is None
            return b"helper stdout", b"helper stderr"

    captured: dict[str, object] = {}

    async def fake_create_subprocess_exec(*argv: str, **kwargs: object) -> FakeProcess:
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return FakeProcess()

    monkeypatch.setattr(WindowsAppContainerBackend, "available", lambda self: True)
    monkeypatch.setattr(
        win_mod.asyncio,
        "create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    result = await WindowsAppContainerBackend().run(_request(tmp_path, policy))

    helper_argv = captured["argv"]
    assert isinstance(helper_argv, tuple)
    assert helper_argv[:3] == (
        sys.executable,
        "-m",
        "opensquilla.sandbox.backend.windows_appcontainer_helper",
    )
    payload = json.loads(helper_argv[3])
    assert payload["argv"] == ["cmd", "/c", "echo", "ok"]
    assert payload["cwd"] == str(tmp_path)
    assert payload["env"] == {"PATH": r"C:\Windows\System32"}
    assert payload["session_id"] == "default"
    assert "SECRET" not in payload["env"]
    assert payload["policy"]["network"] == "proxy_allowlist"
    assert payload["policy"]["network_proxy"] == {"host": "127.0.0.1", "port": 18080}
    assert payload["policy"]["mounts"] == [
        {"host": str(tmp_path), "sandbox": "/workspace", "mode": "rw"}
    ]
    assert payload["timeout"] == 5.0
    assert captured["kwargs"] == {
        "stdout": asyncio.subprocess.PIPE,
        "stderr": asyncio.subprocess.PIPE,
    }
    assert result.returncode == 9
    assert result.stdout == "helper stdout"
    assert result.stderr == "helper stderr"
    assert result.backend_used == "windows_appcontainer"
    assert result.policy_used == policy.summary()


@pytest.mark.asyncio
async def test_run_timeout_kills_helper(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from opensquilla.sandbox.backend import windows_appcontainer as win_mod
    from opensquilla.sandbox.backend.windows_appcontainer import (
        WindowsAppContainerBackend,
    )

    class HangingProcess:
        returncode = None
        killed = False

        async def communicate(self, input: bytes | None = None) -> tuple[bytes, bytes]:
            await asyncio.sleep(60)
            return b"", b""

        def kill(self) -> None:
            self.killed = True

        async def wait(self) -> None:
            return None

    proc = HangingProcess()

    async def fake_create_subprocess_exec(*argv: str, **kwargs: object) -> HangingProcess:
        return proc

    monkeypatch.setattr(WindowsAppContainerBackend, "available", lambda self: True)
    monkeypatch.setattr(
        win_mod.asyncio,
        "create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    result = await WindowsAppContainerBackend().run(
        _request(tmp_path, _policy(tmp_path, wall_timeout_s=0.01))
    )

    assert proc.killed is True
    assert result.returncode == 124
    assert result.timed_out is True
    assert result.backend_used == "windows_appcontainer"


def test_run_raises_when_backend_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from opensquilla.sandbox.backend.windows_appcontainer import (
        WindowsAppContainerBackend,
    )

    monkeypatch.setattr(WindowsAppContainerBackend, "available", lambda self: False)

    with pytest.raises(SandboxBackendError, match="windows_appcontainer backend unavailable"):
        asyncio.run(WindowsAppContainerBackend().run(_request(tmp_path)))


def test_helper_non_windows_fails_closed_without_subprocess_fallback(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    from opensquilla.sandbox.backend import windows_appcontainer_helper as helper

    def forbidden_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise AssertionError("helper must not fall back to subprocess.run")

    monkeypatch.setattr(helper.sys, "platform", "linux")
    monkeypatch.setattr(subprocess, "run", forbidden_run)

    payload = json.dumps(
        {
            "argv": ["cmd", "/c", "echo", "ok"],
            "cwd": str(tmp_path),
            "env": {},
            "policy": _policy(tmp_path).summary(),
            "timeout": 5.0,
        }
    )

    with pytest.raises(SystemExit) as exc_info:
        helper.main([payload])

    captured = capsys.readouterr()
    assert exc_info.value.code != 0
    assert "only runs on native Windows" in captured.err


def test_helper_requires_exactly_one_payload_arg(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from opensquilla.sandbox.backend import windows_appcontainer_helper as helper

    monkeypatch.setattr(helper.sys, "platform", "win32")

    with pytest.raises(SystemExit) as exc_info:
        helper.main([])

    captured = capsys.readouterr()
    assert exc_info.value.code != 0
    assert "expects one JSON payload argument" in captured.err


def test_helper_parse_payload_defaults_session_id(tmp_path: Path) -> None:
    from opensquilla.sandbox.backend import windows_appcontainer_helper as helper

    payload = helper._parse_payload(
        [
            json.dumps(
                {
                    "argv": ["cmd", "/c", "echo", "ok"],
                    "cwd": str(tmp_path),
                    "env": {},
                    "policy": _policy(tmp_path).summary(),
                    "timeout": 5.0,
                }
            )
        ]
    )

    assert payload.session_id == "default"


@pytest.mark.parametrize("session_id", ["", 123])
def test_helper_parse_payload_rejects_invalid_session_id(
    session_id: object,
    tmp_path: Path,
) -> None:
    from opensquilla.sandbox.backend import windows_appcontainer_helper as helper

    with pytest.raises(SystemExit, match="session_id must be a non-empty string"):
        helper._parse_payload(
            [
                json.dumps(
                    {
                        "argv": ["cmd", "/c", "echo", "ok"],
                        "cwd": str(tmp_path),
                        "env": {},
                        "policy": _policy(tmp_path).summary(),
                        "session_id": session_id,
                        "timeout": 5.0,
                    }
                )
            ]
        )


def test_helper_requires_proxy_spec_for_proxy_allowlist(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    from opensquilla.sandbox.backend import windows_appcontainer_helper as helper
    from opensquilla.sandbox.backend.windows_support import WindowsSandboxSupport

    monkeypatch.setattr(helper.sys, "platform", "win32")
    monkeypatch.setattr(
        helper,
        "probe_windows_sandbox_support",
        lambda: WindowsSandboxSupport(
            is_windows=True,
            ctypes_available=True,
            appcontainer_enforced=False,
            restricted_token_enforced=False,
            proxy_allowlist_enforced=False,
        ),
    )
    payload = json.dumps(
        {
            "argv": ["cmd", "/c", "echo", "ok"],
            "cwd": str(tmp_path),
            "env": {},
            "policy": _policy(tmp_path, network=NetworkMode.PROXY_ALLOWLIST).summary(),
            "timeout": 5.0,
        }
    )

    with pytest.raises(SystemExit) as exc_info:
        helper.main([payload])

    captured = capsys.readouterr()
    assert exc_info.value.code != 0
    assert "proxy_allowlist requires network_proxy" in captured.err


def test_helper_rejects_before_run_when_appcontainer_enforcement_missing(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    from opensquilla.sandbox.backend import windows_appcontainer_helper as helper
    from opensquilla.sandbox.backend.windows_support import WindowsSandboxSupport

    def forbidden_run(payload: object) -> None:
        raise AssertionError("helper must not run without declared enforcement")

    monkeypatch.setattr(helper.sys, "platform", "win32")
    monkeypatch.setattr(
        helper,
        "probe_windows_sandbox_support",
        lambda: WindowsSandboxSupport(
            is_windows=True,
            ctypes_available=True,
            appcontainer_enforced=False,
            restricted_token_enforced=False,
            proxy_allowlist_enforced=False,
        ),
    )
    monkeypatch.setattr(helper, "_run_appcontainer", forbidden_run)
    payload = json.dumps(
        {
            "argv": ["cmd", "/c", "echo", "ok"],
            "cwd": str(tmp_path),
            "env": {},
            "policy": _policy(tmp_path).summary(),
            "timeout": 5.0,
        }
    )

    with pytest.raises(SystemExit) as exc_info:
        helper.main([payload])

    captured = capsys.readouterr()
    assert exc_info.value.code != 0
    assert "cannot enforce AppContainer policy yet" in captured.err


def test_helper_normalizes_backend_errors_to_stderr_exit_1(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    from opensquilla.sandbox.backend import windows_appcontainer_helper as helper
    from opensquilla.sandbox.backend.windows_support import WindowsSandboxSupport

    def failing_run(payload: object) -> None:
        _ = payload
        raise SandboxBackendError("profile creation failed")

    monkeypatch.setattr(helper.sys, "platform", "win32")
    monkeypatch.setattr(
        helper,
        "probe_windows_sandbox_support",
        lambda: WindowsSandboxSupport(
            is_windows=True,
            ctypes_available=True,
            appcontainer_enforced=True,
            restricted_token_enforced=False,
            proxy_allowlist_enforced=True,
        ),
    )
    monkeypatch.setattr(helper, "_run_appcontainer", failing_run)
    payload = json.dumps(
        {
            "argv": ["cmd", "/c", "echo", "ok"],
            "cwd": str(tmp_path),
            "env": {},
            "policy": _policy(tmp_path).summary(),
            "timeout": 5.0,
        }
    )

    with pytest.raises(SystemExit) as exc_info:
        helper.main([payload])

    captured = capsys.readouterr()
    assert exc_info.value.code == 1
    assert "profile creation failed" in captured.err


def test_helper_run_appcontainer_creates_profile_grants_and_launches(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    from opensquilla.sandbox.backend import windows_appcontainer_helper as helper
    from opensquilla.sandbox.backend.windows_primitives import AppContainerLaunchResult

    granted: list[tuple[object, str]] = []
    captured_launch: dict[str, object] = {}

    async def fake_grant_policy_paths(payload: object, appcontainer_sid: str) -> None:
        granted.append((payload, appcontainer_sid))

    async def fake_launch_appcontainer_process(**kwargs: object) -> AppContainerLaunchResult:
        captured_launch.update(kwargs)
        return AppContainerLaunchResult(returncode=7, stdout=b"out", stderr=b"err")

    payload = helper._HelperPayload(
        argv=("cmd", "/c", "echo", "ok"),
        cwd=tmp_path,
        env={"PATH": r"C:\Windows\System32"},
        policy=_policy(tmp_path).summary(),
        session_id="agent:main",
        appcontainer_profile_name=None,
        appcontainer_sid=None,
        timeout=5.0,
    )

    monkeypatch.setattr(helper, "appcontainer_profile_name", lambda session_id: "profile")
    monkeypatch.setattr(helper, "ensure_appcontainer_profile", lambda profile_name: "sid")
    monkeypatch.setattr(helper, "_grant_policy_paths", fake_grant_policy_paths)
    monkeypatch.setattr(
        helper,
        "launch_appcontainer_process",
        fake_launch_appcontainer_process,
    )

    with pytest.raises(SystemExit) as exc_info:
        helper._run_appcontainer(payload)

    captured = capsys.readouterr()
    assert exc_info.value.code == 7
    assert captured.out == "out"
    assert captured.err == "err"
    assert granted == [(payload, "sid")]
    assert captured_launch == {
        "profile_name": "profile",
        "argv": ("cmd", "/c", "echo", "ok"),
        "cwd": tmp_path,
        "env": {"PATH": r"C:\Windows\System32"},
        "timeout": 5.0,
    }


@pytest.mark.asyncio
async def test_grant_policy_paths_grants_each_mount_mode(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from opensquilla.sandbox.backend import windows_appcontainer_helper as helper

    ro_path = tmp_path / "ro"
    ro_path.mkdir()
    grants: list[tuple[Path, str, str]] = []

    async def fake_grant_path_to_appcontainer(
        path: Path,
        appcontainer_sid: str,
        *,
        mode: str,
    ) -> None:
        grants.append((path, appcontainer_sid, mode))

    monkeypatch.setattr(helper, "grant_path_to_appcontainer", fake_grant_path_to_appcontainer)
    payload = helper._HelperPayload(
        argv=("cmd",),
        cwd=tmp_path,
        env={},
        policy={
            "mounts": [
                {"host": str(tmp_path), "sandbox": "/workspace", "mode": "rw"},
                {"host": str(ro_path), "sandbox": "/ro", "mode": "ro"},
            ]
        },
        session_id="default",
        appcontainer_profile_name=None,
        appcontainer_sid=None,
        timeout=5.0,
    )

    await helper._grant_policy_paths(payload, "S-1-15-2-123")

    assert grants == [
        (tmp_path, "S-1-15-2-123", "rw"),
        (ro_path, "S-1-15-2-123", "ro"),
    ]


@pytest.mark.asyncio
async def test_grant_policy_paths_rejects_unknown_mount_mode(tmp_path: Path) -> None:
    from opensquilla.sandbox.backend import windows_appcontainer_helper as helper

    payload = helper._HelperPayload(
        argv=("cmd",),
        cwd=tmp_path,
        env={},
        policy={
            "mounts": [
                {"host": str(tmp_path), "sandbox": "/workspace", "mode": "execute"}
            ]
        },
        session_id="default",
        appcontainer_profile_name=None,
        appcontainer_sid=None,
        timeout=5.0,
    )

    with pytest.raises(SystemExit, match="unknown mount mode"):
        await helper._grant_policy_paths(payload, "S-1-15-2-123")


def test_helper_valid_policy_requires_declared_appcontainer_enforcement(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    from opensquilla.sandbox.backend import windows_appcontainer_helper as helper
    from opensquilla.sandbox.backend.windows_support import WindowsSandboxSupport

    monkeypatch.setattr(helper.sys, "platform", "win32")
    monkeypatch.setattr(
        helper,
        "probe_windows_sandbox_support",
        lambda: WindowsSandboxSupport(
            is_windows=True,
            ctypes_available=True,
            appcontainer_enforced=False,
            restricted_token_enforced=False,
            proxy_allowlist_enforced=False,
        ),
    )
    payload = json.dumps(
        {
            "argv": ["cmd", "/c", "echo", "ok"],
            "cwd": str(tmp_path),
            "env": {},
            "policy": _policy(tmp_path).summary(),
            "timeout": 5.0,
        }
    )

    with pytest.raises(SystemExit) as exc_info:
        helper.main([payload])

    captured = capsys.readouterr()
    assert exc_info.value.code != 0
    assert "cannot enforce AppContainer policy yet" in captured.err
