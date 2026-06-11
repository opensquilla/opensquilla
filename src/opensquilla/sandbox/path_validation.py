"""Sandbox mount visibility checks for host paths."""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePath, PurePosixPath
from typing import Any, Literal

from opensquilla.sandbox.sensitive_paths import sensitive_path_marker

MountAccess = Literal["ro", "rw"]
MountStatus = Literal["allowed", "request", "blocked"]
DecisionPath = Path | PurePosixPath


@dataclass(frozen=True)
class MountDecision:
    status: MountStatus
    normalized_path: str
    access: MountAccess
    reason: str = ""


_POSIX_BLOCKED_PREFIXES: tuple[str, ...] = (
    "/etc",
    "/proc",
    "/sys",
    "/dev",
    "/boot",
    "/root",
    "/var/run/docker.sock",
    "/run/docker.sock",
)
def normalize_mount_access(value: Any, default: MountAccess = "ro") -> MountAccess:
    return "rw" if isinstance(value, str) and value.lower().strip() == "rw" else default


def normalize_path(path: str | os.PathLike[str]) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def _looks_like_posix_rooted_text(path: str) -> bool:
    return os.name == "nt" and path.startswith("/") and not path.startswith("//")


def _normalize_decision_path(path: str | os.PathLike[str]) -> DecisionPath:
    if isinstance(path, str) and _looks_like_posix_rooted_text(path):
        return PurePosixPath(path)
    if isinstance(path, PurePosixPath) and not isinstance(path, Path):
        return path
    return normalize_path(path)


def is_relative_to_path(candidate: PurePath, root: PurePath) -> bool:
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def decide_path_access(
    path: str | os.PathLike[str],
    *,
    workspace: str | os.PathLike[str] | None,
    mounts: Iterable[Any] = (),
    write: bool = False,
) -> MountDecision:
    """Return whether *path* is visible in the active sandbox mount view."""

    access: MountAccess = "rw" if write else "ro"
    normalized = _normalize_decision_path(path)
    normalized_text = str(normalized)
    workspace_path = _normalize_decision_path(workspace) if workspace is not None else None

    if workspace_path is not None and is_relative_to_path(normalized, workspace_path):
        marker = sensitive_path_marker(normalized_text, workspace=str(workspace_path))
        if marker is not None:
            return MountDecision(
                status="blocked",
                normalized_path=normalized_text,
                access=access,
                reason="sensitive_path",
            )
        return MountDecision(
            status="allowed",
            normalized_path=normalized_text,
            access=access,
        )

    if _is_blocked_path(normalized, workspace_path):
        return MountDecision(
            status="blocked",
            normalized_path=normalized_text,
            access=access,
            reason="sensitive_path",
        )

    matching_mounts = [
        (mount_root, mount_access)
        for mount_root, mount_access in _iter_mount_roots(mounts)
        if is_relative_to_path(normalized, mount_root)
    ]
    if matching_mounts:
        _mount_root, mount_access = max(
            matching_mounts,
            key=lambda item: len(item[0].parts),
        )
        if not write or mount_access == "rw":
            return MountDecision(
                status="allowed",
                normalized_path=normalized_text,
                access=access,
            )
        return MountDecision(
            status="request",
            normalized_path=normalized_text,
            access="rw",
            reason="mount_requires_write_access",
        )

    return MountDecision(
        status="request",
        normalized_path=normalized_text,
        access=access,
        reason="outside_sandbox_mounts",
    )


def _iter_mount_roots(mounts: Iterable[Any]) -> Iterable[tuple[DecisionPath, MountAccess]]:
    for item in mounts:
        raw_path: Any
        raw_access: Any
        if isinstance(item, Mapping):
            raw_path = item.get("path") or item.get("host_path")
            raw_access = item.get("access") or item.get("mode")
        else:
            raw_path = getattr(item, "path", None) or getattr(item, "host_path", None)
            raw_access = getattr(item, "access", None) or getattr(item, "mode", None)
        if not isinstance(raw_path, (str, os.PathLike)):
            continue
        try:
            root = _normalize_decision_path(raw_path)
        except (OSError, RuntimeError):
            continue
        yield root, normalize_mount_access(raw_access)


def _is_blocked_path(path: PurePath, workspace: PurePath | None) -> bool:
    if _is_filesystem_root(path):
        return True
    marker = sensitive_path_marker(
        str(path),
        workspace=str(workspace) if workspace is not None else None,
    )
    if marker is not None:
        return True
    normalized = str(path).replace("\\", "/")
    for prefix in _POSIX_BLOCKED_PREFIXES:
        if normalized == prefix or normalized.startswith(prefix.rstrip("/") + "/"):
            return True
    return _is_windows_sensitive_path(str(path))


def _is_filesystem_root(path: PurePath) -> bool:
    try:
        if not path.anchor:
            return False
        return path == type(path)(path.anchor)
    except (OSError, RuntimeError, ValueError):
        return False


def _is_windows_sensitive_path(raw_path: str) -> bool:
    from opensquilla.sandbox.backend.windows_default_roots import windows_sensitive_marker

    return windows_sensitive_marker(raw_path) is not None


__all__ = [
    "MountAccess",
    "MountDecision",
    "MountStatus",
    "decide_path_access",
    "is_relative_to_path",
    "normalize_mount_access",
    "normalize_path",
]
