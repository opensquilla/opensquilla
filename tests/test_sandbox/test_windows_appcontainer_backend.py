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


def test_helper_requires_proxy_spec_for_proxy_allowlist(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    from opensquilla.sandbox.backend import windows_appcontainer_helper as helper

    monkeypatch.setattr(helper.sys, "platform", "win32")
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


def test_helper_valid_policy_still_fails_unenforceable(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    from opensquilla.sandbox.backend import windows_appcontainer_helper as helper

    monkeypatch.setattr(helper.sys, "platform", "win32")
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
