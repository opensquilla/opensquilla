from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from opensquilla.sandbox.run_mode import RunMode
from opensquilla.sandbox.types import (
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
    assert payload["policy"]["network"] == "none"


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

    async def fake_exec(*argv, stdout=None, stderr=None):
        captured["argv"] = argv
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
