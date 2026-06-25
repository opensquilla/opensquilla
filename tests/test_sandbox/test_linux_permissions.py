from __future__ import annotations

from pathlib import Path

from opensquilla.sandbox.backend.linux_permissions import compile_linux_permissions
from opensquilla.sandbox.types import (
    MountSpec,
    NetworkMode,
    ResourceLimits,
    SandboxPolicy,
    SecurityLevel,
)


def _policy(tmp_path: Path, *, network: NetworkMode = NetworkMode.NONE) -> SandboxPolicy:
    return SandboxPolicy(
        level=SecurityLevel.STANDARD,
        network=network,
        mounts=(
            MountSpec(
                host_path=tmp_path,
                sandbox_path=Path("/workspace"),
                mode="rw",
                required=True,
            ),
            MountSpec(
                host_path=tmp_path / "docs",
                sandbox_path=Path("/workspace/docs"),
                mode="ro",
                required=False,
            ),
        ),
        workspace_rw=True,
        tmp_writable=True,
        limits=ResourceLimits(wall_timeout_s=30),
        env_allowlist=("PATH", "HOME"),
        require_approval=False,
    )


def test_compile_linux_permissions_splits_mount_modes(tmp_path: Path) -> None:
    compiled = compile_linux_permissions(_policy(tmp_path))

    assert str(tmp_path) in [str(root.host_path) for root in compiled.write_roots]
    assert str(tmp_path / "docs") in [str(root.host_path) for root in compiled.read_roots]
    assert compiled.env_allowlist == ("PATH", "HOME")
    assert compiled.tmp_writable is True


def test_compile_linux_permissions_adds_protected_subpaths_under_writable_roots(
    tmp_path: Path,
) -> None:
    compiled = compile_linux_permissions(_policy(tmp_path))

    protected = {path.as_posix() for path in compiled.protected_subpaths}

    assert (tmp_path / ".git").as_posix() in protected
    assert (tmp_path / ".codex").as_posix() in protected
    assert (tmp_path / ".agents").as_posix() in protected


def test_compile_linux_permissions_upgrades_duplicate_host_aliases_to_writable(
    tmp_path: Path,
) -> None:
    policy = SandboxPolicy(
        level=SecurityLevel.STANDARD,
        network=NetworkMode.NONE,
        mounts=(
            MountSpec(
                host_path=tmp_path,
                sandbox_path=Path("/workspace"),
                mode="rw",
                required=True,
            ),
            MountSpec(
                host_path=tmp_path,
                sandbox_path=tmp_path,
                mode="ro",
                required=False,
            ),
        ),
        workspace_rw=True,
        tmp_writable=True,
        limits=ResourceLimits(wall_timeout_s=30),
        env_allowlist=("PATH", "HOME"),
        require_approval=False,
    )

    compiled = compile_linux_permissions(policy)

    write_targets = {root.sandbox_path.as_posix() for root in compiled.write_roots}
    read_targets = {root.sandbox_path.as_posix() for root in compiled.read_roots}
    assert tmp_path.as_posix() in write_targets
    assert tmp_path.as_posix() not in read_targets


def test_compile_linux_permissions_preserves_network_mode(tmp_path: Path) -> None:
    compiled = compile_linux_permissions(_policy(tmp_path, network=NetworkMode.PROXY_ALLOWLIST))

    assert compiled.network == NetworkMode.PROXY_ALLOWLIST


def test_compile_linux_permissions_detects_root_read_mount(tmp_path: Path) -> None:
    policy = SandboxPolicy(
        level=SecurityLevel.STANDARD,
        network=NetworkMode.NONE,
        mounts=(
            MountSpec(
                host_path=Path("/"),
                sandbox_path=Path("/"),
                mode="ro",
                required=True,
            ),
            MountSpec(
                host_path=tmp_path,
                sandbox_path=Path("/workspace"),
                mode="rw",
                required=True,
            ),
        ),
        workspace_rw=True,
        tmp_writable=True,
        limits=ResourceLimits(wall_timeout_s=30),
        env_allowlist=("PATH",),
        require_approval=False,
    )

    compiled = compile_linux_permissions(policy)

    assert compiled.read_all is True


def test_compile_linux_permissions_adds_sensitive_deny_roots(tmp_path: Path) -> None:
    compiled = compile_linux_permissions(_policy(tmp_path))

    denied = {path.as_posix() for path in compiled.denied_roots}

    assert "/etc" not in denied
    assert "/etc/shadow" in denied
    assert str(tmp_path) not in denied
