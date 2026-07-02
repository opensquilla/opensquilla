"""Linux runtime permission model for the sandbox helper."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from opensquilla.sandbox.backend.linux_paths import canonical_linux_mount
from opensquilla.sandbox.sensitive_paths import linux_runtime_sensitive_deny_roots
from opensquilla.sandbox.types import (
    MountSpec,
    NetworkMode,
    SandboxPolicy,
)

PROTECTED_SUBPATH_NAMES = (".git", ".codex", ".agents")


@dataclass(frozen=True)
class LinuxRoot:
    host_path: Path
    sandbox_path: Path
    required: bool


@dataclass(frozen=True)
class LinuxPermissions:
    read_roots: tuple[LinuxRoot, ...]
    write_roots: tuple[LinuxRoot, ...]
    denied_roots: tuple[Path, ...]
    protected_subpaths: tuple[Path, ...]
    env_allowlist: tuple[str, ...]
    network: NetworkMode
    tmp_writable: bool
    wall_timeout_s: float
    read_all: bool = False
    denied_globs: tuple[str, ...] = ()


def compile_linux_permissions(policy: SandboxPolicy) -> LinuxPermissions:
    read_roots: list[LinuxRoot] = []
    write_roots: list[LinuxRoot] = []
    writable_host_paths = {mount.host_path for mount in policy.mounts if mount.mode == "rw"}
    for mount in policy.mounts:
        root = _linux_root(mount)
        if mount.mode == "rw" or mount.host_path in writable_host_paths:
            write_roots.append(root)
        else:
            read_roots.append(root)

    protected_subpaths = tuple(
        path
        for root in write_roots
        for base in _protected_subpath_bases(root)
        for path in _protected_subpaths_for_root(base)
    )

    return LinuxPermissions(
        read_roots=tuple(read_roots),
        write_roots=tuple(write_roots),
        denied_roots=linux_runtime_sensitive_deny_roots(
            workspace=_workspace_mount_path(write_roots),
        ),
        denied_globs=tuple(getattr(policy, "unreadable_globs", ())),
        protected_subpaths=protected_subpaths,
        env_allowlist=tuple(policy.env_allowlist),
        network=policy.network,
        tmp_writable=policy.tmp_writable,
        wall_timeout_s=policy.limits.wall_timeout_s,
        read_all=_has_root_read_mount(read_roots),
    )


def _linux_root(mount: MountSpec) -> LinuxRoot:
    mount = canonical_linux_mount(mount)
    return LinuxRoot(
        host_path=mount.host_path,
        sandbox_path=Path(str(mount.sandbox_path)),
        required=mount.required,
    )


def _protected_subpaths_for_root(root: Path) -> tuple[Path, ...]:
    return tuple(root / name for name in PROTECTED_SUBPATH_NAMES)


def _protected_subpath_bases(root: LinuxRoot) -> tuple[Path, ...]:
    if root.host_path == root.sandbox_path:
        return (root.host_path,)
    return (root.host_path, root.sandbox_path)


def _workspace_mount_path(write_roots: list[LinuxRoot]) -> Path | None:
    for root in write_roots:
        if root.sandbox_path.as_posix() == "/workspace":
            return root.host_path
    return write_roots[0].host_path if write_roots else None


def _has_root_read_mount(read_roots: list[LinuxRoot]) -> bool:
    return any(
        root.host_path == Path("/") and root.sandbox_path == Path("/")
        for root in read_roots
    )
