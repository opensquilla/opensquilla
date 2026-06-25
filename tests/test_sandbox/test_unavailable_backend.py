from __future__ import annotations

from pathlib import Path

import pytest

from opensquilla.sandbox.types import (
    MountSpec,
    NetworkMode,
    ResourceLimits,
    SandboxBackendError,
    SandboxPolicy,
    SandboxRequest,
    SecurityLevel,
)


def _request(tmp_path: Path) -> SandboxRequest:
    return SandboxRequest(
        argv=("cmd", "/c", "echo", "ok"),
        cwd=tmp_path,
        action_kind="shell.exec",
        policy=SandboxPolicy(
            level=SecurityLevel.STANDARD,
            network=NetworkMode.NONE,
            mounts=(
                MountSpec(
                    host_path=tmp_path,
                    sandbox_path=Path("/workspace"),
                    mode="rw",
                    required=True,
                ),
            ),
            workspace_rw=True,
            tmp_writable=True,
            limits=ResourceLimits(wall_timeout_s=1.0),
            env_allowlist=("PATH",),
            require_approval=False,
        ),
    )


@pytest.mark.asyncio
async def test_unavailable_backend_fails_closed_without_running_command(
    tmp_path: Path,
) -> None:
    from opensquilla.sandbox.backend.unavailable import UnavailableBackend

    backend = UnavailableBackend("no real sandbox backend is available")

    with pytest.raises(SandboxBackendError, match="no real sandbox backend"):
        await backend.run(_request(tmp_path))


def test_auto_backend_failure_includes_windows_setup_diagnostics(monkeypatch) -> None:
    from opensquilla.sandbox import backend as backend_mod
    from opensquilla.sandbox.backend import windows_default_support
    from opensquilla.sandbox.backend.windows_default import (
        WindowsDefaultBackend,
    )
    from opensquilla.sandbox.config import SandboxSettings

    monkeypatch.setattr(backend_mod.sys, "platform", "win32")
    monkeypatch.setattr(WindowsDefaultBackend, "available", lambda self: False)
    monkeypatch.setattr(windows_default_support, "_ctypes_available", lambda: True)
    monkeypatch.setattr(windows_default_support, "_token_api_available", lambda: False)
    monkeypatch.setattr(windows_default_support, "_acl_api_available", lambda: True)

    with pytest.raises(SandboxBackendError) as exc_info:
        backend_mod.select_backend(SandboxSettings(sandbox=True, backend="auto"))

    message = str(exc_info.value)
    assert "no real sandbox backend" in message
    assert "Windows sandbox setup diagnostics" in message
    assert "windows_default" in message
    assert "network boundary" in message
