from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from opensquilla.sandbox.types import (
    MountSpec,
    NetworkMode,
    NetworkProxySpec,
    ResourceLimits,
    SandboxPolicy,
    SandboxRequest,
    SecurityLevel,
)


def _policy(tmp_path: Path) -> SandboxPolicy:
    return SandboxPolicy(
        level=SecurityLevel.STANDARD,
        network=NetworkMode.PROXY_ALLOWLIST,
        network_proxy=NetworkProxySpec(host="127.0.0.1", port=18080),
        mounts=(
            MountSpec(host_path=tmp_path, sandbox_path=Path("/workspace"), mode="rw"),
        ),
        workspace_rw=True,
        tmp_writable=True,
        limits=ResourceLimits(wall_timeout_s=5),
        env_allowlist=("PATH",),
        require_approval=False,
    )


def _request(tmp_path: Path) -> SandboxRequest:
    return SandboxRequest(
        argv=("cmd", "/c", "echo", "ok"),
        cwd=tmp_path,
        action_kind="shell.exec",
        policy=_policy(tmp_path),
        env={"PATH": r"C:\Windows\System32"},
    )


def test_appcontainer_identity_contains_profile_and_sid(monkeypatch) -> None:
    from opensquilla.sandbox.backend import windows_primitives as primitives

    monkeypatch.setattr(
        primitives,
        "ensure_appcontainer_profile",
        lambda name: "S-1-15-2-123",
    )

    identity = primitives.prepare_appcontainer_identity("agent:main:webchat:abc")

    assert identity.profile_name == "opensquilla-sandbox-agent-main-webchat-abc"
    assert identity.appcontainer_sid == "S-1-15-2-123"


@pytest.mark.asyncio
async def test_backend_payload_includes_prepared_appcontainer_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from opensquilla.sandbox.backend import windows_appcontainer as win_mod
    from opensquilla.sandbox.backend.windows_appcontainer import WindowsAppContainerBackend

    class FakeProcess:
        returncode = 0

        async def communicate(self, input: bytes | None = None) -> tuple[bytes, bytes]:
            assert input is None
            return b"", b""

    captured: dict[str, object] = {}

    async def fake_create_subprocess_exec(*argv: str, **kwargs: object) -> FakeProcess:
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return FakeProcess()

    monkeypatch.setattr(WindowsAppContainerBackend, "available", lambda self: True)
    monkeypatch.setattr(
        win_mod,
        "prepare_appcontainer_identity",
        lambda session_id: SimpleNamespace(
            profile_name="opensquilla-sandbox-default",
            appcontainer_sid="S-1-15-2-123",
        ),
    )
    monkeypatch.setattr(
        win_mod.asyncio,
        "create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    await WindowsAppContainerBackend().run(_request(tmp_path))

    helper_argv = captured["argv"]
    assert isinstance(helper_argv, tuple)
    assert helper_argv[:3] == (
        sys.executable,
        "-m",
        "opensquilla.sandbox.backend.windows_appcontainer_helper",
    )
    payload = json.loads(helper_argv[3])
    assert payload["appcontainer_profile_name"] == "opensquilla-sandbox-default"
    assert payload["appcontainer_sid"] == "S-1-15-2-123"
    assert captured["kwargs"] == {
        "stdout": asyncio.subprocess.PIPE,
        "stderr": asyncio.subprocess.PIPE,
    }
