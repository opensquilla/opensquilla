"""Shared per-entry formatting for resilient directory listings."""

from __future__ import annotations

import errno
import stat
from pathlib import Path

_BROKEN_SYMLINK_ERRNOS = frozenset({errno.ENOENT, errno.ENOTDIR, errno.ELOOP})


def format_directory_entry(entry: Path) -> tuple[bool, str]:
    """Return ``(is_directory, display_line)`` without failing on child metadata."""

    try:
        mode = entry.lstat().st_mode
    except OSError:
        return False, f"[file] {entry.name} (metadata unavailable)"

    if stat.S_ISLNK(mode):
        try:
            size = entry.stat().st_size
        except OSError as exc:
            if exc.errno in _BROKEN_SYMLINK_ERRNOS:
                return False, f"[link] {entry.name} (broken symlink)"
            return False, f"[link] {entry.name} (target metadata unavailable)"
        return False, f"[link] {entry.name} ({size} bytes target)"

    if stat.S_ISDIR(mode):
        return True, f"[dir]  {entry.name}/"

    try:
        size = entry.stat().st_size
    except OSError:
        return False, f"[file] {entry.name} (size unavailable)"
    return False, f"[file] {entry.name} ({size} bytes)"


__all__ = ["format_directory_entry"]
