from __future__ import annotations

import sys
from pathlib import Path

import pytest

from opensquilla.sandbox.backend.windows_acl import (
    build_icacls_grant_argv,
    build_icacls_traverse_argv,
    grant_path_to_appcontainer,
)
from opensquilla.sandbox.types import SandboxBackendError


def test_build_icacls_grant_argv_uses_modify_rights_for_read_write() -> None:
    path = Path("C:/workspace")

    argv = build_icacls_grant_argv(path, "S-1-15-2-123", mode="rw")

    assert argv == (
        "icacls",
        str(path),
        "/grant",
        "*S-1-15-2-123:(OI)(CI)M",
        "/T",
        "/C",
    )


def test_build_icacls_grant_argv_uses_read_execute_rights_for_read_only() -> None:
    path = Path("C:/workspace")

    argv = build_icacls_grant_argv(path, "S-1-15-2-456", mode="ro")

    assert "*S-1-15-2-456:(OI)(CI)RX" in argv


def test_build_icacls_grant_argv_rejects_unknown_mode() -> None:
    with pytest.raises(ValueError, match="unsupported ACL mode"):
        build_icacls_grant_argv(Path("C:/workspace"), "S-1-15-2-123", mode="execute")


def test_build_icacls_grant_argv_rejects_non_appcontainer_sid() -> None:
    with pytest.raises(ValueError, match="appcontainer SID must start with S-1-15-2-"):
        build_icacls_grant_argv(Path("C:/workspace"), "S-1-5-32-544", mode="rw")


@pytest.mark.asyncio
async def test_grant_path_to_appcontainer_fails_closed_on_non_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_create_subprocess_exec(*args: object, **kwargs: object) -> object:
        raise AssertionError("subprocess should not be invoked")

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(
        "asyncio.create_subprocess_exec",
        fail_create_subprocess_exec,
    )

    with pytest.raises(SandboxBackendError, match="Windows ACL grants require native Windows"):
        await grant_path_to_appcontainer(Path("/workspace"), "S-1-15-2-123", mode="rw")


@pytest.mark.asyncio
async def test_grant_path_to_appcontainer_grants_parent_traverse_for_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    target = tmp_path / "Users" / "alice" / ".opensquilla" / "workspace"
    target.mkdir(parents=True)
    captured: list[tuple[tuple[str, ...], Path]] = []

    async def fake_run_icacls(argv: tuple[str, ...], path: Path) -> None:
        captured.append((argv, path))

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(
        "opensquilla.sandbox.backend.windows_acl._run_icacls",
        fake_run_icacls,
    )

    await grant_path_to_appcontainer(target, "S-1-15-2-123", mode="rw")

    traverse_paths = [
        parent for parent in (*reversed(target.parent.parents), target.parent) if parent.exists()
    ]
    assert captured == [
        *[
            (build_icacls_traverse_argv(parent, "S-1-15-2-123"), parent)
            for parent in traverse_paths
        ],
        (build_icacls_grant_argv(target, "S-1-15-2-123", mode="rw"), target),
    ]
