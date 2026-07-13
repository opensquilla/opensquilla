"""Canonical filesystem permissions shared by sandbox backends and direct tools.

The default Linux workspace profile mirrors Codex's normal sandbox posture:
the host filesystem is readable, only declared roots are writable, and agent
metadata inside writable project roots is re-protected as read-only.  Explicit
denied-read entries are policy, not a built-in list of "sensitive" path names.
"""

from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Iterable

PROTECTED_METADATA_NAMES = (".git", ".agents", ".codex")


class FileSystemAccess(StrEnum):
    """Effective access granted to one canonical host path."""

    DENY = "deny"
    READ = "read"
    WRITE = "write"


@dataclass(frozen=True)
class FileSystemPermissionEntry:
    """An access rule rooted at ``path``.

    More-specific paths win.  If two entries have identical specificity, the
    later declaration wins, allowing protected and denied subpaths to be
    layered over broad writable roots.
    """

    path: Path
    access: FileSystemAccess


@dataclass(frozen=True)
class FileSystemPermissionProfile:
    """Resolved filesystem policy for one sandboxed operation."""

    entries: tuple[FileSystemPermissionEntry, ...]
    denied_read_globs: tuple[str, ...] = ()

    @classmethod
    def workspace(
        cls,
        *,
        workspace: Path,
        readable_roots: Iterable[Path] = (),
        writable_roots: Iterable[Path] = (),
        denied_read_roots: Iterable[Path] = (),
        denied_read_globs: Iterable[str] = (),
        host_root_readonly: bool = True,
        tmp_writable: bool = True,
        protect_metadata: bool = True,
    ) -> FileSystemPermissionProfile:
        """Build the default workspace-write profile used by Codex on Linux."""

        workspace = _canonical(workspace)
        declared_writable = [workspace, *(_canonical(path) for path in writable_roots)]
        if tmp_writable:
            declared_writable.append(_canonical(Path("/tmp")))
            if raw_tmpdir := os.environ.get("TMPDIR"):
                declared_writable.append(_canonical(Path(raw_tmpdir)))
        declared_writable = list(dict.fromkeys(declared_writable))

        entries: list[FileSystemPermissionEntry] = []
        if host_root_readonly:
            entries.append(FileSystemPermissionEntry(Path("/"), FileSystemAccess.READ))
        entries.extend(
            FileSystemPermissionEntry(_canonical(path), FileSystemAccess.READ)
            for path in readable_roots
        )
        entries.extend(
            FileSystemPermissionEntry(path, FileSystemAccess.WRITE)
            for path in declared_writable
        )
        if protect_metadata:
            entries.extend(
                FileSystemPermissionEntry(root / name, FileSystemAccess.READ)
                for root in declared_writable
                for name in PROTECTED_METADATA_NAMES
            )
        entries.extend(
            FileSystemPermissionEntry(_canonical(path), FileSystemAccess.DENY)
            for path in denied_read_roots
        )
        return cls(
            entries=tuple(entries),
            denied_read_globs=tuple(str(pattern) for pattern in denied_read_globs),
        )

    @classmethod
    def read_only(
        cls,
        *,
        readable_roots: Iterable[Path] = (Path("/"),),
        denied_read_roots: Iterable[Path] = (),
        denied_read_globs: Iterable[str] = (),
    ) -> FileSystemPermissionProfile:
        entries = [
            FileSystemPermissionEntry(_canonical(path), FileSystemAccess.READ)
            for path in readable_roots
        ]
        entries.extend(
            FileSystemPermissionEntry(_canonical(path), FileSystemAccess.DENY)
            for path in denied_read_roots
        )
        return cls(tuple(entries), tuple(str(pattern) for pattern in denied_read_globs))

    @classmethod
    def full_access(cls) -> FileSystemPermissionProfile:
        """Return an unrestricted profile for explicit sandbox-disabled mode."""

        return cls((FileSystemPermissionEntry(Path("/"), FileSystemAccess.WRITE),))

    def resolve(self, path: Path) -> FileSystemAccess:
        """Return effective access for ``path`` using canonical longest match."""

        candidate = _canonical(path)
        candidate_text = candidate.as_posix()
        if any(
            fnmatch.fnmatchcase(candidate_text, _canonical_glob(pattern))
            for pattern in self.denied_read_globs
        ):
            return FileSystemAccess.DENY

        matches = (
            (len(root.parts), index, entry.access)
            for index, entry in enumerate(self.entries)
            if candidate.is_relative_to(root := _canonical(entry.path))
        )
        return max(
            matches,
            key=lambda match: (match[0], match[1]),
            default=(0, -1, FileSystemAccess.DENY),
        )[2]

    @property
    def has_denied_reads(self) -> bool:
        return bool(self.denied_read_globs) or any(
            entry.access is FileSystemAccess.DENY for entry in self.entries
        )

    @property
    def unsandboxed_execution_allowed(self) -> bool:
        """Codex forbids a no-sandbox override when denied reads are active."""

        return not self.has_denied_reads

    @property
    def denied_read_roots(self) -> tuple[Path, ...]:
        return tuple(
            _canonical(entry.path)
            for entry in self.entries
            if entry.access is FileSystemAccess.DENY
        )


def _canonical(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def _canonical_glob(pattern: str) -> str:
    return os.path.expanduser(pattern).replace(os.sep, "/")


__all__ = [
    "FileSystemAccess",
    "FileSystemPermissionEntry",
    "FileSystemPermissionProfile",
    "PROTECTED_METADATA_NAMES",
]
