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
def _reset_sandbox_runtime():
    reset_runtime()
    yield
    reset_runtime()


def test_windows_auto_backend_disables_sandbox_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from opensquilla.sandbox import integration

    monkeypatch.setattr(integration.sys, "platform", "win32")

    runtime = configure_runtime(
        SandboxSettings(sandbox=True, security_grading=True, backend="auto"),
        approval_queue=_FakeApprovalQueue(),
        workspace=tmp_path,
    )

    assert runtime.settings.sandbox is False
    assert runtime.settings.security_grading is False
    assert runtime.effective.sandbox_enabled is False
    assert runtime.effective.grading_enabled is False
    assert runtime.backend.name == "noop"


def test_macos_auto_backend_selects_seatbelt_when_available(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from opensquilla.sandbox import backend as backend_mod
    from opensquilla.sandbox import integration

    monkeypatch.setattr(integration.sys, "platform", "darwin")
    monkeypatch.setattr(backend_mod.sys, "platform", "darwin")
    monkeypatch.setattr(
        backend_mod.SeatbeltBackend,
        "available",
        lambda self: True,
    )

    runtime = configure_runtime(
        SandboxSettings(sandbox=True, security_grading=True, backend="auto"),
        approval_queue=_FakeApprovalQueue(),
        workspace=tmp_path,
    )

    assert runtime.settings.sandbox is True
    assert runtime.settings.security_grading is True
    assert runtime.effective.sandbox_enabled is True
    assert runtime.effective.grading_enabled is True
    assert runtime.backend.name == "seatbelt"


def test_explicit_macos_seatbelt_backend_still_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from opensquilla.sandbox import backend as backend_mod
    from opensquilla.sandbox import integration

    monkeypatch.setattr(integration.sys, "platform", "darwin")
    monkeypatch.setattr(backend_mod.sys, "platform", "darwin")
    monkeypatch.setattr(
        backend_mod.SeatbeltBackend,
        "available",
        lambda self: False,
    )

    with pytest.raises(SandboxBackendError, match="sandbox backend 'seatbelt' is unavailable"):
        configure_runtime(
            SandboxSettings(sandbox=True, security_grading=True, backend="seatbelt"),
            approval_queue=_FakeApprovalQueue(),
            workspace=tmp_path,
        )


def test_linux_auto_backend_without_real_backend_still_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from opensquilla.sandbox import backend as backend_mod
    from opensquilla.sandbox import integration

    monkeypatch.setattr(integration.sys, "platform", "linux")
    monkeypatch.setattr(backend_mod.sys, "platform", "linux")
    monkeypatch.setattr(
        backend_mod.BubblewrapBackend,
        "available",
        lambda self: False,
    )

    with pytest.raises(SandboxBackendError, match="no real sandbox backend"):
        configure_runtime(
            SandboxSettings(sandbox=True, security_grading=True, backend="auto"),
            approval_queue=_FakeApprovalQueue(),
            workspace=tmp_path,
        )
