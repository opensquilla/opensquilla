from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest

from opensquilla.sandbox.config import SandboxSettings
from opensquilla.sandbox.types import (
    MountSpec,
    NetworkMode,
    ResourceLimits,
    SandboxBackendError,
    SandboxPolicy,
    SandboxRequest,
    SecurityLevel,
)


def _policy(workspace: Path, *, wall_timeout_s: float = 5.0) -> SandboxPolicy:
    return SandboxPolicy(
        level=SecurityLevel.STANDARD,
        network=NetworkMode.NONE,
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


def _request(tmp_path: Path, *, wall_timeout_s: float = 5.0) -> SandboxRequest:
    return SandboxRequest(
        argv=("cmd", "/c", "echo", "ok"),
        cwd=tmp_path,
        action_kind="shell.exec",
        policy=_policy(tmp_path, wall_timeout_s=wall_timeout_s),
        env={"PATH": r"C:\Windows\System32", "SECRET": "not-forwarded"},
    )


def test_windows_auto_selects_restricted_token_when_appcontainer_unavailable(
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


def test_windows_auto_fails_closed_when_restricted_token_unavailable(
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
    monkeypatch.setattr(WindowsRestrictedTokenBackend, "available", lambda self: False)

    with pytest.raises(SandboxBackendError, match="no real sandbox backend"):
        backend_mod.select_backend(SandboxSettings(sandbox=True, backend="auto"))


def test_explicit_windows_restricted_token_selects_backend_when_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.sandbox import backend as backend_mod
    from opensquilla.sandbox.backend.windows_restricted_token import (
        WindowsRestrictedTokenBackend,
    )

    monkeypatch.setattr(WindowsRestrictedTokenBackend, "available", lambda self: True)

    backend = backend_mod.select_backend(
        SandboxSettings(sandbox=True, backend="windows_restricted_token")
    )

    assert isinstance(backend, WindowsRestrictedTokenBackend)


def test_explicit_windows_restricted_token_fails_closed_when_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.sandbox import backend as backend_mod
    from opensquilla.sandbox.backend.windows_restricted_token import (
        WindowsRestrictedTokenBackend,
    )

    monkeypatch.setattr(WindowsRestrictedTokenBackend, "available", lambda self: False)

    with pytest.raises(
        SandboxBackendError,
        match="sandbox backend 'windows_restricted_token' is unavailable",
    ):
        backend_mod.select_backend(
            SandboxSettings(sandbox=True, backend="windows_restricted_token")
        )


@pytest.mark.asyncio
async def test_run_invokes_helper_and_serializes_request(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from opensquilla.sandbox.backend import windows_restricted_token as win_mod
    from opensquilla.sandbox.backend.windows_restricted_token import (
        WindowsRestrictedTokenBackend,
    )

    class FakeProcess:
        returncode = 7

        async def communicate(self, input: bytes | None = None) -> tuple[bytes, bytes]:
            assert input is None
            return b"helper stdout", b"helper stderr"

    captured: dict[str, object] = {}

    async def fake_create_subprocess_exec(*argv: str, **kwargs: object) -> FakeProcess:
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return FakeProcess()

    monkeypatch.setattr(WindowsRestrictedTokenBackend, "available", lambda self: True)
    monkeypatch.setattr(
        win_mod.asyncio,
        "create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    result = await WindowsRestrictedTokenBackend().run(_request(tmp_path))

    helper_argv = captured["argv"]
    assert isinstance(helper_argv, tuple)
    assert helper_argv[:3] == (
        sys.executable,
        "-m",
        "opensquilla.sandbox.backend.windows_restricted_token_helper",
    )
    payload = json.loads(helper_argv[3])
    assert payload["argv"] == ["cmd", "/c", "echo", "ok"]
    assert payload["cwd"] == str(tmp_path)
    assert payload["env"] == {"PATH": r"C:\Windows\System32"}
    assert "SECRET" not in payload["env"]
    assert payload["policy"]["network"] == "none"
    assert payload["timeout"] == 5.0
    assert captured["kwargs"] == {
        "stdout": asyncio.subprocess.PIPE,
        "stderr": asyncio.subprocess.PIPE,
    }
    assert result.returncode == 7
    assert result.stdout == "helper stdout"
    assert result.stderr == "helper stderr"
    assert result.backend_used == "windows_restricted_token"
    assert result.policy_used == _policy(tmp_path).summary()


@pytest.mark.asyncio
async def test_run_timeout_kills_helper(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from opensquilla.sandbox.backend import windows_restricted_token as win_mod
    from opensquilla.sandbox.backend.windows_restricted_token import (
        WindowsRestrictedTokenBackend,
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

    monkeypatch.setattr(WindowsRestrictedTokenBackend, "available", lambda self: True)
    monkeypatch.setattr(
        win_mod.asyncio,
        "create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    result = await WindowsRestrictedTokenBackend().run(
        _request(tmp_path, wall_timeout_s=0.01)
    )

    assert proc.killed is True
    assert result.returncode == 124
    assert result.timed_out is True
    assert result.backend_used == "windows_restricted_token"


def test_run_raises_when_backend_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from opensquilla.sandbox.backend.windows_restricted_token import (
        WindowsRestrictedTokenBackend,
    )

    monkeypatch.setattr(WindowsRestrictedTokenBackend, "available", lambda self: False)

    with pytest.raises(SandboxBackendError, match="windows_restricted_token backend unavailable"):
        asyncio.run(WindowsRestrictedTokenBackend().run(_request(tmp_path)))


def test_helper_non_windows_fails_closed_without_subprocess_fallback(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    from opensquilla.sandbox.backend import windows_restricted_token_helper as helper

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
