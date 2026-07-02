from __future__ import annotations

from pathlib import Path

import pytest

from opensquilla.sandbox.config import SandboxSettings
from opensquilla.sandbox.integration import configure_runtime, reset_runtime
from opensquilla.sandbox.types import SandboxBackendError


class _FakeApprovalQueue:
    def request(self, namespace: str = "exec.approval", params: dict | None = None) -> str:
        return "approval:test"

    async def wait(self, approval_id: str, timeout: float | None = None) -> bool:
        return False

    def resolve(self, approval_id: str, approved: bool) -> None:
        return None


@pytest.fixture(autouse=True)
def _reset_runtime():
    reset_runtime()
    yield
    reset_runtime()


def test_windows_auto_backend_selects_windows_default_when_available(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from opensquilla.sandbox import backend as backend_mod
    from opensquilla.sandbox.backend.windows_default import WindowsDefaultBackend

    monkeypatch.setattr(backend_mod.sys, "platform", "win32")
    monkeypatch.setattr(WindowsDefaultBackend, "available", lambda self: True)

    runtime = configure_runtime(
        SandboxSettings(sandbox=True, security_grading=True, backend="auto"),
        approval_queue=_FakeApprovalQueue(),
        workspace=tmp_path,
    )

    assert runtime.backend.name == "windows_default"


def test_explicit_windows_default_fails_closed_when_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from opensquilla.sandbox import backend as backend_mod
    from opensquilla.sandbox.backend.windows_default import WindowsDefaultBackend

    monkeypatch.setattr(backend_mod.sys, "platform", "win32")
    monkeypatch.setattr(WindowsDefaultBackend, "available", lambda self: False)

    with pytest.raises(SandboxBackendError, match="windows_default.*unavailable"):
        configure_runtime(
            SandboxSettings(sandbox=True, security_grading=True, backend="windows_default"),
            approval_queue=_FakeApprovalQueue(),
            workspace=tmp_path,
        )


def test_removed_windows_restricted_token_config_raises_migration_error() -> None:
    with pytest.raises(ValueError, match="windows_restricted_token.*windows_default"):
        SandboxSettings(backend="windows_restricted_token")


def test_full_host_access_still_uses_noop_on_windows(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from opensquilla.sandbox import backend as backend_mod

    monkeypatch.setattr(backend_mod.sys, "platform", "win32")

    runtime = configure_runtime(
        SandboxSettings(run_mode="full"),
        approval_queue=_FakeApprovalQueue(),
        workspace=tmp_path,
    )

    assert runtime.effective.sandbox_enabled is False
    assert runtime.backend.name == "noop"
