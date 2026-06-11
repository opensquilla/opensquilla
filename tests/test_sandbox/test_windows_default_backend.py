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
