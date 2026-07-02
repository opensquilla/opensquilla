from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from opensquilla.sandbox.run_mode import RunMode
from opensquilla.sandbox.types import (
    MountSpec,
    NetworkMode,
    ResourceLimits,
    SandboxBackendError,
    SandboxPolicy,
    SandboxRequest,
    SecurityLevel,
)


def _policy() -> SandboxPolicy:
    return SandboxPolicy(
        level=SecurityLevel.STANDARD,
        network=NetworkMode.NONE,
        mounts=(),
        workspace_rw=True,
        tmp_writable=True,
        limits=ResourceLimits(wall_timeout_s=2),
        env_allowlist=("PATH", "TEMP", "TMP", "PIP_CACHE_DIR"),
        require_approval=False,
    )


def _request(tmp_path: Path) -> SandboxRequest:
    return SandboxRequest(
        argv=("python", "-c", "print('ok')"),
        cwd=tmp_path,
        action_kind="shell.exec",
        policy=_policy(),
        env={"PATH": r"C:\Windows\System32"},
        run_mode=RunMode.TRUSTED.value,
    )


def test_payload_contains_cache_env_and_run_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.sandbox.backend import windows_default as mod

    monkeypatch.setattr(mod, "_support_ready", lambda: True)
    monkeypatch.setattr(mod, "_capability_store_path", lambda: tmp_path / "cap_sids.json")

    payload = mod._payload_for_request(_request(tmp_path))

    assert payload["backend"] == "windows_default"
    assert payload["runMode"] == "trusted"
    assert payload["cwd"] == str(tmp_path)
    assert payload["env"]["TEMP"] == str(tmp_path / ".opensquilla-cache" / "temp")
    assert payload["env"]["PIP_CACHE_DIR"] == str(tmp_path / ".opensquilla-cache" / "pip")
    assert payload["env"]["APPDATA"] == str(
        tmp_path / ".opensquilla-cache" / "home" / "AppData" / "Roaming"
    )
    assert payload["env"]["LOCALAPPDATA"] == str(
        tmp_path / ".opensquilla-cache" / "home" / "AppData" / "Local"
    )
    assert payload["env"]["npm_config_prefix"] == str(
        tmp_path / ".opensquilla-cache" / "npm" / "prefix"
    )
    assert payload["policy"]["network"] == "none"


def test_payload_rehomes_user_state_for_regular_windows_commands(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.sandbox.backend import windows_default as mod

    policy = SandboxPolicy(
        level=SecurityLevel.STANDARD,
        network=NetworkMode.NONE,
        mounts=(),
        workspace_rw=True,
        tmp_writable=True,
        limits=ResourceLimits(wall_timeout_s=2),
        env_allowlist=("PATH", "HOME", "USERPROFILE", "HOMEDRIVE", "HOMEPATH"),
        require_approval=False,
    )
    request = SandboxRequest(
        argv=("git", "ls-remote", "https://github.com/opensquilla/opensquilla.git", "HEAD"),
        cwd=tmp_path,
        action_kind="shell.exec",
        policy=policy,
        env={
            "PATH": r"C:\Program Files\Git\cmd",
            "HOME": r"C:\SandboxUser\me\.opensquilla",
            "USERPROFILE": r"C:\SandboxUser\me",
            "HOMEDRIVE": "C:",
            "HOMEPATH": r"\SandboxUser\me",
        },
        run_mode=RunMode.TRUSTED.value,
    )
    monkeypatch.setattr(mod, "_support_ready", lambda: True)
    monkeypatch.setattr(mod, "_capability_store_path", lambda: tmp_path / "cap_sids.json")

    payload = mod._payload_for_request(request)

    home = tmp_path / ".opensquilla-cache" / "home"
    assert payload["env"]["HOME"] == str(home)
    assert payload["env"]["USERPROFILE"] == str(home)
    assert payload["env"]["HOMEDRIVE"] == home.drive
    assert payload["env"]["HOMEPATH"] == str(home)[len(home.drive) :]
    assert payload["env"]["GIT_CONFIG_GLOBAL"] == str(
        tmp_path / ".opensquilla-cache" / "git" / "config"
    )


def test_payload_preserves_windows_process_base_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.sandbox.backend import windows_default as mod

    windows_root = tmp_path / "Windows"
    windows_root.mkdir()
    monkeypatch.setenv("SystemRoot", str(windows_root))
    monkeypatch.setenv("WINDIR", str(windows_root))
    monkeypatch.setenv("ComSpec", str(windows_root / "System32" / "cmd.exe"))

    request = _request(tmp_path)
    monkeypatch.setattr(mod, "_support_ready", lambda: True)
    monkeypatch.setattr(mod, "_capability_store_path", lambda: tmp_path / "cap_sids.json")

    payload = mod._payload_for_request(request)

    assert payload["env"]["SystemRoot"] == str(windows_root)
    assert payload["env"]["WINDIR"] == str(windows_root)
    assert payload["env"]["ComSpec"] == str(windows_root / "System32" / "cmd.exe")


def test_payload_prepends_real_windows_tool_paths_and_grants_user_tool_acl(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.sandbox.backend import windows_default as mod

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    program_files = tmp_path / "Program Files"
    git_cmd = program_files / "Git" / "cmd"
    git_cmd.mkdir(parents=True)
    (git_cmd / "git.exe").write_text("", encoding="utf-8")
    userprofile = tmp_path / "Users" / "lrk"
    local_appdata = userprofile / "AppData" / "Local"
    node_bin = local_appdata / "OpenAI" / "Codex" / "runtimes" / "cua_node" / "abc" / "bin"
    node_bin.mkdir(parents=True)
    (node_bin / "node.exe").write_text("", encoding="utf-8")
    (node_bin / "npm.cmd").write_text("@echo off\r\n", encoding="utf-8")
    windows_apps = tmp_path / "WindowsApps"
    windows_apps.mkdir()
    (windows_apps / "git.cmd").write_text("@echo off\r\n", encoding="utf-8")

    monkeypatch.setenv("ProgramFiles", str(program_files))
    monkeypatch.setenv("LOCALAPPDATA", str(local_appdata))
    monkeypatch.setattr(mod, "_support_ready", lambda: True)
    monkeypatch.setattr(mod, "_capability_store_path", lambda: tmp_path / "cap_sids.json")
    original_sensitive_marker = mod._acl_sensitive_marker
    monkeypatch.setattr(
        mod,
        "_acl_sensitive_marker",
        lambda path: "windows_system"
        if Path(path).resolve(strict=False) == git_cmd.resolve(strict=False)
        else original_sensitive_marker(path),
    )

    request = _request(workspace)
    request = SandboxRequest(
        argv=request.argv,
        cwd=request.cwd,
        action_kind=request.action_kind,
        policy=request.policy,
        env={
            "PATH": str(windows_apps),
            "ProgramFiles": str(program_files),
            "LOCALAPPDATA": str(local_appdata),
            "USERPROFILE": str(userprofile),
        },
        run_mode=request.run_mode,
    )

    payload = mod._payload_for_request(request)

    path_entries = payload["env"]["PATH"].split(";")
    assert path_entries[:2] == [str(git_cmd), str(node_bin)]
    assert str(windows_apps) in path_entries[2:]

    grants = {
        grant["path"]: grant["access"]
        for grant in payload["policy"]["windowsAclPlan"]["autoGrants"]
    }
    assert grants[str(userprofile / "AppData")] == "RX"
    assert grants[str(local_appdata)] == "RX"
    assert grants[str(local_appdata / "OpenAI")] == "RX"
    assert grants[str(node_bin)] == "RX"
    assert str(git_cmd) not in grants


def test_payload_discovers_codex_bundled_git_and_node_tools(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.sandbox.backend import windows_default as mod

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    userprofile = tmp_path / "Users" / "lrk"
    codex_runtime = (
        userprofile / ".cache" / "codex-runtimes" / "codex-primary-runtime" / "dependencies"
    )
    git_cmd = codex_runtime / "native" / "git" / "cmd"
    node_bin = codex_runtime / "node" / "bin"
    git_cmd.mkdir(parents=True)
    node_bin.mkdir(parents=True)
    (git_cmd / "git.exe").write_text("", encoding="utf-8")
    (node_bin / "node.exe").write_text("", encoding="utf-8")
    (node_bin / "npm.cmd").write_text("@echo off\r\n", encoding="utf-8")
    windows_apps = tmp_path / "Microsoft" / "WindowsApps"
    windows_apps.mkdir(parents=True)
    (windows_apps / "git.cmd").write_text("@echo off\r\n", encoding="utf-8")

    monkeypatch.setenv("ProgramFiles", str(tmp_path / "missing-program-files"))
    monkeypatch.setenv("ProgramFiles(x86)", str(tmp_path / "missing-program-files-x86"))
    monkeypatch.setenv("USERPROFILE", str(userprofile))
    monkeypatch.setenv("LOCALAPPDATA", str(userprofile / "AppData" / "Local"))
    monkeypatch.setenv("APPDATA", str(userprofile / "AppData" / "Roaming"))
    monkeypatch.setattr(mod, "_support_ready", lambda: True)
    monkeypatch.setattr(mod, "_capability_store_path", lambda: tmp_path / "cap_sids.json")

    request = _request(workspace)
    request = SandboxRequest(
        argv=request.argv,
        cwd=request.cwd,
        action_kind=request.action_kind,
        policy=request.policy,
        env={
            "PATH": str(windows_apps),
            "USERPROFILE": str(userprofile),
            "LOCALAPPDATA": str(userprofile / "AppData" / "Local"),
            "APPDATA": str(userprofile / "AppData" / "Roaming"),
            "ProgramFiles": str(tmp_path / "missing-program-files"),
            "ProgramFiles(x86)": str(tmp_path / "missing-program-files-x86"),
        },
        run_mode=request.run_mode,
    )

    payload = mod._payload_for_request(request)

    path_entries = payload["env"]["PATH"].split(";")
    assert path_entries[:2] == [str(git_cmd), str(node_bin)]
    assert str(windows_apps) in path_entries[2:]

    grants = {
        grant["path"]: grant["access"]
        for grant in payload["policy"]["windowsAclPlan"]["autoGrants"]
    }
    assert grants[str(userprofile / ".cache")] == "RX"
    assert grants[str(userprofile / ".cache" / "codex-runtimes")] == "RX"
    assert grants[str(git_cmd)] == "RX"
    assert grants[str(node_bin)] == "RX"


def test_payload_encodes_stdin_as_base64(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.sandbox.backend import windows_default as mod

    request = _request(tmp_path)
    request = SandboxRequest(
        argv=request.argv,
        cwd=request.cwd,
        action_kind=request.action_kind,
        policy=request.policy,
        stdin=b"hello from stdin\r\n",
        env=request.env,
        run_mode=request.run_mode,
    )
    monkeypatch.setattr(mod, "_support_ready", lambda: True)
    monkeypatch.setattr(mod, "_capability_store_path", lambda: tmp_path / "cap_sids.json")

    payload = mod._payload_for_request(request)

    assert payload["stdinBase64"] == "aGVsbG8gZnJvbSBzdGRpbg0K"


@pytest.mark.asyncio
async def test_backend_fails_closed_when_setup_is_not_ready(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.sandbox.backend import windows_default as mod
    from opensquilla.sandbox.backend.windows_default import WindowsDefaultBackend

    monkeypatch.setattr(mod, "_support_ready", lambda: False)

    with pytest.raises(SandboxBackendError, match="windows_default backend unavailable"):
        await WindowsDefaultBackend().run(_request(tmp_path))


@pytest.mark.asyncio
async def test_backend_returns_helper_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.sandbox.backend import windows_default as mod
    from opensquilla.sandbox.backend.windows_default import WindowsDefaultBackend

    class _Proc:
        returncode = 7

        async def communicate(self):
            return b"out", b"err"

    captured = {}

    async def fake_exec(*argv, stdout=None, stderr=None, env=None):
        captured["argv"] = argv
        captured["env"] = env
        return _Proc()

    monkeypatch.setattr(mod, "_support_ready", lambda: True)
    monkeypatch.setattr(mod, "_capability_store_path", lambda: tmp_path / "cap_sids.json")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    result = await WindowsDefaultBackend().run(_request(tmp_path))

    assert result.returncode == 7
    assert result.stdout == "out"
    assert result.stderr == "err"
    assert result.backend_used == "windows_default"
    assert "opensquilla.sandbox.backend.windows_default_runner" in captured["argv"]
    assert "--payload-env" in captured["argv"]
    payload_env = captured["env"]["OPENSQUILLA_WINDOWS_DEFAULT_PAYLOAD"]
    assert '"argv":["python","-c","print(\'ok\')"]' in payload_env


@pytest.mark.asyncio
async def test_backend_waits_for_helper_grace_beyond_command_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.sandbox.backend import windows_default as mod
    from opensquilla.sandbox.backend.windows_default import WindowsDefaultBackend

    class _Proc:
        returncode = 0

        async def communicate(self):
            return b"", b""

    captured = {}

    async def fake_exec(*argv, stdout=None, stderr=None, env=None):
        captured["env"] = env
        return _Proc()

    async def fake_wait_for(awaitable, timeout=None):
        captured["wait_timeout"] = timeout
        return await awaitable

    request = _request(tmp_path)
    monkeypatch.setattr(mod, "_support_ready", lambda: True)
    monkeypatch.setattr(mod, "_capability_store_path", lambda: tmp_path / "cap_sids.json")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)

    result = await WindowsDefaultBackend().run(request)

    payload = json.loads(captured["env"]["OPENSQUILLA_WINDOWS_DEFAULT_PAYLOAD"])
    assert result.returncode == 0
    assert payload["timeout"] == request.policy.limits.wall_timeout_s
    assert captured["wait_timeout"] > payload["timeout"]


def test_payload_contains_required_workspace_and_runtime_acl_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.sandbox.backend import windows_default as mod

    monkeypatch.setattr(mod, "_support_ready", lambda: True)
    monkeypatch.setattr(
        mod,
        "_python_executable",
        lambda: tmp_path / "runtime" / "Scripts" / "python.exe",
    )
    monkeypatch.setattr(mod, "_capability_store_path", lambda: tmp_path / "cap_sids.json")
    (tmp_path / "runtime" / "Scripts").mkdir(parents=True)
    (tmp_path / "runtime" / "Scripts" / "python.exe").write_text("", encoding="utf-8")

    payload = mod._payload_for_request(_request(tmp_path))

    plan = payload["policy"]["windowsAclPlan"]
    grant_paths = {grant["path"]: grant["access"] for grant in plan["autoGrants"]}
    assert grant_paths[str(tmp_path)] == "RWX"
    assert grant_paths[str(tmp_path / ".opensquilla-cache")] == "RWX"
    assert grant_paths[str(tmp_path / "runtime" / "Scripts")] == "RX"
    assert plan["capabilitySids"]
    assert plan["grantCurrentUserAccess"] is True


def test_payload_includes_offline_identity_boundary_when_marker_has_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.sandbox.backend import windows_default as mod
    from opensquilla.sandbox.backend.windows_default_network import WindowsNetworkSetup
    from opensquilla.sandbox.backend.windows_default_setup import write_setup_marker

    marker = tmp_path / "setup_marker.json"
    write_setup_marker(
        marker,
        network=WindowsNetworkSetup(
            offline_user_sid="S-1-5-21-100-200-300-400",
            allowed_proxy_ports=(48123,),
            allow_local_binding=False,
            firewall_rule_version=5,
            wfp_rule_version=2,
            offline_username="OpenSquillaSandbox",
            protected_password="protected",
        ),
    )
    monkeypatch.setattr(mod, "_support_ready", lambda: True)
    monkeypatch.setattr(mod, "_capability_store_path", lambda: tmp_path / "cap_sids.json")
    monkeypatch.setattr(mod, "default_setup_marker_path", lambda: marker)

    payload = mod._payload_for_request(_request(tmp_path))

    assert payload["policy"]["windowsNetworkBoundary"]["offlineUserSid"] == (
        "S-1-5-21-100-200-300-400"
    )


def test_payload_adds_runtime_readonly_roots_as_deny_write_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.sandbox.backend import windows_default as mod

    runtime_scripts = tmp_path / "runtime" / "Scripts"
    source_root = tmp_path / "src" / "opensquilla"
    runtime_scripts.mkdir(parents=True)
    source_root.mkdir(parents=True)

    monkeypatch.setattr(mod, "_support_ready", lambda: True)
    monkeypatch.setattr(mod, "_capability_store_path", lambda: tmp_path / "cap_sids.json")
    monkeypatch.setattr(
        mod,
        "_runtime_readonly_roots",
        lambda: (runtime_scripts, source_root),
    )

    payload = mod._payload_for_request(_request(tmp_path))

    assert payload["policy"]["windowsAclPlan"]["denyWritePaths"] == [
        str(runtime_scripts),
        str(source_root),
    ]


def test_payload_adds_readonly_policy_mounts_as_deny_write_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.sandbox.backend import windows_default as mod

    readonly_root = tmp_path / "readonly"
    readonly_root.mkdir()
    policy = SandboxPolicy(
        level=SecurityLevel.STANDARD,
        network=NetworkMode.NONE,
        mounts=(
            MountSpec(
                host_path=readonly_root,
                sandbox_path=readonly_root,
                mode="ro",
                required=True,
            ),
        ),
        workspace_rw=True,
        tmp_writable=True,
        limits=ResourceLimits(wall_timeout_s=2),
        env_allowlist=("PATH",),
        require_approval=False,
    )
    request = SandboxRequest(
        argv=("python", "-c", "print('ok')"),
        cwd=tmp_path,
        action_kind="shell.exec",
        policy=policy,
        env={"PATH": r"C:\Windows\System32"},
        run_mode=RunMode.TRUSTED.value,
    )

    monkeypatch.setattr(mod, "_support_ready", lambda: True)
    monkeypatch.setattr(mod, "_capability_store_path", lambda: tmp_path / "cap_sids.json")
    monkeypatch.setattr(mod, "_runtime_readonly_roots", lambda: ())

    payload = mod._payload_for_request(request)

    assert payload["policy"]["windowsAclPlan"]["denyWritePaths"] == [str(readonly_root)]


def test_payload_grants_opensquilla_workspace_parent_for_traversal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.sandbox.backend import windows_default as mod

    state_root = tmp_path / ".opensquilla"
    workspace = state_root / "workspace"
    workspace.mkdir(parents=True)
    request = _request(workspace)
    monkeypatch.setattr(mod, "_support_ready", lambda: True)
    monkeypatch.setattr(mod, "_capability_store_path", lambda: tmp_path / "cap_sids.json")

    payload = mod._payload_for_request(request)

    grants = {
        grant["path"]: grant["access"]
        for grant in payload["policy"]["windowsAclPlan"]["autoGrants"]
    }
    assert grants[str(state_root)] == "RX"
    assert grants[str(workspace)] == "RWX"


def test_payload_grants_process_runtime_roots_rx(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.sandbox.backend import windows_default as mod

    powershell_root = tmp_path / "Windows" / "System32" / "WindowsPowerShell" / "v1.0"
    program_files = tmp_path / "Program Files"
    program_data = tmp_path / "ProgramData"
    for path in (powershell_root, program_files, program_data):
        path.mkdir(parents=True)
    powershell = powershell_root / "powershell.exe"
    powershell.write_text("", encoding="utf-8")

    request = _request(tmp_path)
    request = SandboxRequest(
        argv=(str(powershell), "-NoLogo", "-Command", "Write-Output ok"),
        cwd=request.cwd,
        action_kind=request.action_kind,
        policy=request.policy,
        env=request.env,
        run_mode=request.run_mode,
    )
    monkeypatch.setattr(mod, "_support_ready", lambda: True)
    monkeypatch.setattr(mod, "_capability_store_path", lambda: tmp_path / "cap_sids.json")
    monkeypatch.setattr(
        mod,
        "process_executable_rx_roots",
        lambda argv, env: (powershell_root, program_files, program_data),
        raising=False,
    )

    payload = mod._payload_for_request(request)

    grants = {
        grant["path"]: grant["access"]
        for grant in payload["policy"]["windowsAclPlan"]["autoGrants"]
    }
    assert grants[str(powershell_root)] == "RX"
    assert grants[str(program_files)] == "RX"
    assert grants[str(program_data)] == "RX"
    assert grants[str(tmp_path)] == "RWX"


def test_payload_does_not_acl_grant_windows_platform_roots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.sandbox.backend import windows_default as mod

    windows_root = tmp_path / "Windows"
    system32 = windows_root / "System32"
    powershell_root = system32 / "WindowsPowerShell" / "v1.0"
    program_files = tmp_path / "Program Files"
    program_data = tmp_path / "ProgramData"
    for path in (powershell_root, program_files, program_data):
        path.mkdir(parents=True)

    request = _request(tmp_path)
    request = SandboxRequest(
        argv=(str(powershell_root / "powershell.exe"), "-Command", "Write-Output ok"),
        cwd=request.cwd,
        action_kind=request.action_kind,
        policy=request.policy,
        env={
            "SystemRoot": str(windows_root),
            "ProgramFiles": str(program_files),
            "ProgramData": str(program_data),
        },
        run_mode=request.run_mode,
    )
    monkeypatch.setattr(mod, "_support_ready", lambda: True)
    monkeypatch.setattr(mod, "_capability_store_path", lambda: tmp_path / "cap_sids.json")

    payload = mod._payload_for_request(request)

    grants = {
        grant["path"]: grant["access"]
        for grant in payload["policy"]["windowsAclPlan"]["autoGrants"]
    }
    assert str(powershell_root) not in grants
    assert str(system32) not in grants
    assert str(windows_root) not in grants
    assert str(program_files) not in grants
    assert str(program_data) not in grants
    assert grants[str(tmp_path)] == "RWX"


def test_trusted_non_sensitive_expansion_auto_grants(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.sandbox.backend import windows_default as mod

    external = tmp_path.parent / f"{tmp_path.name}-external-cache"
    external.mkdir()
    request = _request(tmp_path)
    request = SandboxRequest(
        argv=request.argv,
        cwd=request.cwd,
        action_kind=request.action_kind,
        policy=request.policy,
        env={"OPENSQUILLA_WINDOWS_SANDBOX_EXPANSION_ROOTS": str(external)},
        run_mode=RunMode.TRUSTED.value,
    )
    monkeypatch.setattr(mod, "_support_ready", lambda: True)
    monkeypatch.setattr(mod, "_capability_store_path", lambda: tmp_path / "cap_sids.json")

    payload = mod._payload_for_request(request)

    paths = {grant["path"] for grant in payload["policy"]["windowsAclPlan"]["autoGrants"]}
    assert str(external) in paths


def test_missing_expansion_roots_are_ignored(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.sandbox.backend import windows_default as mod

    missing = tmp_path.parent / f"{tmp_path.name}-deleted-probe.txt"
    request = _request(tmp_path)
    request = SandboxRequest(
        argv=request.argv,
        cwd=request.cwd,
        action_kind=request.action_kind,
        policy=request.policy,
        env={"OPENSQUILLA_WINDOWS_SANDBOX_EXPANSION_ROOTS": str(missing)},
        run_mode=RunMode.TRUSTED.value,
    )
    monkeypatch.setattr(mod, "_support_ready", lambda: True)
    monkeypatch.setattr(mod, "_capability_store_path", lambda: tmp_path / "cap_sids.json")

    payload = mod._payload_for_request(request)

    paths = {grant["path"] for grant in payload["policy"]["windowsAclPlan"]["autoGrants"]}
    assert str(missing) not in paths


def test_standard_non_sensitive_expansion_requires_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.sandbox.backend import windows_default as mod

    external = tmp_path.parent / f"{tmp_path.name}-external-cache"
    external.mkdir()
    request = _request(tmp_path)
    request = SandboxRequest(
        argv=request.argv,
        cwd=request.cwd,
        action_kind=request.action_kind,
        policy=request.policy,
        env={"OPENSQUILLA_WINDOWS_SANDBOX_EXPANSION_ROOTS": str(external)},
        run_mode=RunMode.STANDARD.value,
    )
    monkeypatch.setattr(mod, "_support_ready", lambda: True)
    monkeypatch.setattr(mod, "_capability_store_path", lambda: tmp_path / "cap_sids.json")

    with pytest.raises(SandboxBackendError, match="ACL approval is required"):
        mod._payload_for_request(request)


def test_windows_filesystem_operation_request_uses_worker_cwd_and_precise_mounts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.sandbox.backend import windows_default as mod
    from opensquilla.sandbox.operation_runtime import SandboxOperation

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "nested" / "notes.txt"
    payload = workspace / ".opensquilla-cache" / "fs-worker" / "payload.json"
    runtime_scripts = tmp_path / "runtime" / "Scripts"
    runtime_scripts.mkdir(parents=True)
    python_exe = runtime_scripts / "python.exe"
    python_exe.write_text("", encoding="utf-8")
    source_root = tmp_path / "src" / "opensquilla"
    source_root.mkdir(parents=True)

    monkeypatch.setattr(mod, "_python_executable", lambda: python_exe)
    monkeypatch.setattr(mod, "_opensquilla_import_roots", lambda: (source_root,))

    operation = SandboxOperation.filesystem(
        kind="write_text",
        workspace=workspace,
        run_mode=RunMode.TRUSTED.value,
        path=target,
        paths=(target,),
        content="hello",
    )

    request = mod._filesystem_operation_request(operation, payload)

    assert request.cwd == workspace / ".opensquilla-cache" / "fs-worker"
    assert request.cwd != workspace
    assert request.run_mode == "trusted"
    mounts = {str(mount.host_path): mount.mode for mount in request.policy.mounts}
    assert mounts[str(workspace)] == "rw"
    assert mounts[str(runtime_scripts)] == "ro"
    assert mounts[str(runtime_scripts.parent)] == "ro"
    assert mounts[str(source_root)] == "ro"
    assert "opensquilla.sandbox.filesystem_worker" in request.argv


def test_windows_filesystem_operation_request_supplies_home_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.sandbox.backend import windows_default as mod
    from opensquilla.sandbox.operation_runtime import SandboxOperation

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "notes.txt"
    target.write_text("notes", encoding="utf-8")
    payload = workspace / ".opensquilla-cache" / "fs-worker" / "payload.json"
    python_exe = tmp_path / "runtime" / "Scripts" / "python.exe"
    python_exe.parent.mkdir(parents=True)
    python_exe.write_text("", encoding="utf-8")

    monkeypatch.setattr(mod, "_python_executable", lambda: python_exe)

    operation = SandboxOperation.filesystem(
        kind="read_file",
        workspace=workspace,
        run_mode=RunMode.TRUSTED.value,
        path=target,
        paths=(target,),
    )

    request = mod._filesystem_operation_request(operation, payload)

    assert request.env["USERPROFILE"] == str(request.cwd)
    assert request.env["HOMEDRIVE"]
    assert request.env["HOMEPATH"]
    assert "USERPROFILE" in request.policy.env_allowlist
    assert "HOMEDRIVE" in request.policy.env_allowlist
    assert "HOMEPATH" in request.policy.env_allowlist


def test_windows_filesystem_operation_missing_read_target_fails_before_acl(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.sandbox.backend import windows_default as mod
    from opensquilla.sandbox.operation_runtime import SandboxOperation

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = tmp_path / "missing-root" / "notes.txt"
    payload = workspace / ".opensquilla-cache" / "fs-worker" / "payload.json"

    def _fail_acl_policy(*args: object, **kwargs: object) -> object:
        raise AssertionError("missing read target should fail before ACL planning")

    monkeypatch.setattr(mod, "_filesystem_operation_policy", _fail_acl_policy)

    operation = SandboxOperation.filesystem(
        kind="read_file",
        workspace=workspace,
        run_mode=RunMode.TRUSTED.value,
        path=target,
        paths=(target,),
        display_path=str(target),
    )

    with pytest.raises(FileNotFoundError, match="File not found"):
        mod._filesystem_operation_request(operation, payload)


def test_windows_filesystem_worker_file_not_found_preserves_error_type() -> None:
    from opensquilla.sandbox.backend import windows_default as mod
    from opensquilla.sandbox.types import SandboxResult

    result = SandboxResult(
        returncode=1,
        stdout="",
        stderr='{"error": "File not found: D:\\\\opensquilla\\\\pyproject.toml", '
        '"type": "FileNotFoundError"}',
        wall_time_s=0.0,
        backend_used="windows_default",
    )

    with pytest.raises(FileNotFoundError, match=r"D:\\opensquilla\\pyproject.toml"):
        mod._raise_filesystem_worker_failure(result)


def test_windows_filesystem_operation_denies_runtime_readonly_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.sandbox.backend import windows_default as mod
    from opensquilla.sandbox.operation_runtime import SandboxOperation

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runtime_scripts = tmp_path / "runtime" / "Scripts"
    runtime_scripts.mkdir(parents=True)
    target = runtime_scripts / "python.exe"
    target.write_text("", encoding="utf-8")
    payload = workspace / ".opensquilla-cache" / "fs-worker" / "payload.json"

    monkeypatch.setattr(mod, "_runtime_readonly_roots", lambda: (runtime_scripts,))

    operation = SandboxOperation.filesystem(
        kind="write_text",
        workspace=workspace,
        run_mode=RunMode.TRUSTED.value,
        path=target,
        paths=(target,),
        content="blocked",
    )

    with pytest.raises(SandboxBackendError, match="read-only runtime"):
        mod._filesystem_operation_request(operation, payload)
