from __future__ import annotations

from pathlib import Path

import pytest

from opensquilla.sandbox.config import SandboxSettings
from opensquilla.sandbox.permissions import (
    FileSystemAccess,
    FileSystemPermissionProfile,
)
from opensquilla.sandbox.policy import build_policy
from opensquilla.sandbox.types import SecurityLevel


def test_workspace_profile_reads_root_and_writes_declared_roots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "repo"
    cache = tmp_path / "cache"
    tmpdir = tmp_path / "tmpdir"
    monkeypatch.setenv("TMPDIR", str(tmpdir))

    profile = FileSystemPermissionProfile.workspace(
        workspace=workspace,
        writable_roots=(cache,),
    )

    assert profile.resolve(Path("/etc/hosts")) is FileSystemAccess.READ
    assert profile.resolve(workspace / "src" / "a.py") is FileSystemAccess.WRITE
    assert profile.resolve(cache / "artifact") is FileSystemAccess.WRITE
    assert profile.resolve(Path("/tmp") / "probe") is FileSystemAccess.WRITE
    assert profile.resolve(tmpdir / "probe") is FileSystemAccess.WRITE


@pytest.mark.parametrize("name", [".git", ".agents", ".codex"])
def test_workspace_profile_reprotects_metadata(tmp_path: Path, name: str) -> None:
    profile = FileSystemPermissionProfile.workspace(workspace=tmp_path)

    assert profile.resolve(tmp_path / name / "config") is FileSystemAccess.READ


def test_explicit_denied_read_prevents_unsandboxed_execution(tmp_path: Path) -> None:
    profile = FileSystemPermissionProfile.workspace(
        workspace=tmp_path,
        denied_read_roots=(tmp_path / "secret",),
    )

    assert profile.resolve(tmp_path / "secret" / "token") is FileSystemAccess.DENY
    assert profile.has_denied_reads
    assert not profile.unsandboxed_execution_allowed


def test_denied_read_glob_takes_precedence_over_writable_root(tmp_path: Path) -> None:
    profile = FileSystemPermissionProfile.workspace(
        workspace=tmp_path,
        denied_read_globs=(str(tmp_path / "**" / "*.pem"),),
    )

    assert profile.resolve(tmp_path / "keys" / "identity.pem") is FileSystemAccess.DENY
    assert profile.resolve(tmp_path / "keys" / "identity.pub") is FileSystemAccess.WRITE


def test_build_policy_carries_the_canonical_workspace_profile(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    cache = tmp_path / "cache"
    policy = build_policy(
        SecurityLevel.STANDARD,
        "shell.exec",
        workspace,
        SandboxSettings(extra_rw_mounts=[str(cache)]),
    )

    assert policy.file_system is not None
    assert policy.file_system.resolve(Path("/etc/hosts")) is FileSystemAccess.READ
    assert policy.file_system.resolve(workspace / "a.py") is FileSystemAccess.WRITE
    assert policy.file_system.resolve(cache / "artifact") is FileSystemAccess.WRITE


def test_disabled_policy_is_the_only_full_access_profile(tmp_path: Path) -> None:
    policy = build_policy(
        SecurityLevel.DISABLED,
        "shell.exec",
        tmp_path,
        SandboxSettings(default_level=SecurityLevel.DISABLED, allow_legacy_mode=True),
    )

    assert policy.file_system is not None
    assert policy.file_system.resolve(Path("/etc/hosts")) is FileSystemAccess.WRITE
