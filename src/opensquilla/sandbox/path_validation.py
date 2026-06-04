"""Sandbox mount visibility checks for host paths."""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any, Literal

from opensquilla.sandbox.sensitive_paths import sensitive_path_marker

MountAccess = Literal["ro", "rw"]
MountStatus = Literal["allowed", "request", "blocked"]


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
_WINDOWS_BLOCKED_PARTS: tuple[tuple[str, ...], ...] = (
    ("windows",),
    ("programdata", "microsoft", "crypto"),
    ("users", "all users", "microsoft", "crypto"),
)
_WINDOWS_CREDENTIAL_PARTS: tuple[str, ...] = (
    ".ssh",
    ".aws",
    ".azure",
    ".kube",
    "gcloud",
    "credentials",
)


def normalize_mount_access(value: Any, default: MountAccess = "ro") -> MountAccess:
    return "rw" if isinstance(value, str) and value.lower().strip() == "rw" else default


def normalize_path(path: str | os.PathLike[str]) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def is_relative_to_path(candidate: Path, root: Path) -> bool:
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
    normalized = normalize_path(path)
    normalized_text = str(normalized)
    workspace_path = normalize_path(workspace) if workspace is not None else None

    if _is_blocked_path(normalized, workspace_path):
        return MountDecision(
            status="blocked",
            normalized_path=normalized_text,
            access=access,
            reason="sensitive_path",
        )

    if workspace_path is not None and is_relative_to_path(normalized, workspace_path):
        return MountDecision(
            status="allowed",
            normalized_path=normalized_text,
            access=access,
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


def _iter_mount_roots(mounts: Iterable[Any]) -> Iterable[tuple[Path, MountAccess]]:
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
            root = normalize_path(raw_path)
        except (OSError, RuntimeError):
            continue
        yield root, normalize_mount_access(raw_access)


def _is_blocked_path(path: Path, workspace: Path | None) -> bool:
    if _is_filesystem_root(path):
        return True
    marker = sensitive_path_marker(str(path), workspace=workspace)
    if marker is not None:
        return True
    normalized = str(path).replace("\\", "/")
    for prefix in _POSIX_BLOCKED_PREFIXES:
        if normalized == prefix or normalized.startswith(prefix.rstrip("/") + "/"):
            return True
    return _is_windows_sensitive_path(str(path))


def _is_filesystem_root(path: Path) -> bool:
    try:
        return path == Path(path.anchor)
    except (OSError, RuntimeError, ValueError):
        return False


def _is_windows_sensitive_path(raw_path: str) -> bool:
    if os.name != "nt" and "\\" not in raw_path and not PureWindowsPath(raw_path).drive:
        return False
    win = PureWindowsPath(raw_path)
    parts = tuple(part.casefold() for part in win.parts if part not in {win.anchor, "\\"})
    if not parts:
        return False
    if len(parts) == 1 and parts[0].endswith(":\\"):
        return True
    for blocked in _WINDOWS_BLOCKED_PARTS:
        if len(parts) >= len(blocked) and parts[: len(blocked)] == blocked:
            return True
    return any(part in _WINDOWS_CREDENTIAL_PARTS for part in parts)


__all__ = [
    "MountAccess",
    "MountDecision",
    "MountStatus",
    "decide_path_access",
    "is_relative_to_path",
    "normalize_mount_access",
    "normalize_path",
]
