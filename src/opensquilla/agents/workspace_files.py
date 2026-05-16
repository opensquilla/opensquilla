"""Agent workspace file helpers shared by registry and adapter surfaces."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any

from opensquilla.agents.scope import resolve_agent_workspace_dir
from opensquilla.identity.bootstrap import (
    CORE_BOOTSTRAP_TEMPLATE_FILENAMES,
    ONE_SHOT_BOOTSTRAP_FILENAME,
    ensure_agent_workspace,
)

WORKSPACE_AGENT_FILE_NAMES = (
    *CORE_BOOTSTRAP_TEMPLATE_FILENAMES,
    ONE_SHOT_BOOTSTRAP_FILENAME,
    "MEMORY.md",
    "memory.md",
)
WORKSPACE_AGENT_FILE_NAME_SET = frozenset(WORKSPACE_AGENT_FILE_NAMES)
ALLOWED_WORKSPACE_FILE_EXTENSIONS = frozenset({".md", ".txt", ".yaml", ".yml", ".j2"})


def workspace_file_root_for_config(config: Any | None, agent_id: str) -> Path | None:
    """Resolve the fallback workspace root for an agent from gateway config."""

    if not getattr(config, "workspace_dir", None):
        return None
    return ensure_agent_workspace(resolve_agent_workspace_dir(agent_id, config)).workspace_dir


def validate_workspace_file_name(name: Any) -> str:
    """Validate a user-facing agent workspace file name."""

    if not isinstance(name, str) or not name:
        raise ValueError("params.name is required")
    if name != Path(name).name or "/" in name or "\\" in name:
        raise ValueError("workspace file name must not contain path separators")
    if name not in WORKSPACE_AGENT_FILE_NAME_SET:
        raise ValueError(f"Unsupported workspace agent file: {name}")
    return name


def validate_workspace_file_extension(name: str) -> None:
    """Validate that the file name extension is editable through RPC."""

    ext = "." + name.rsplit(".", 1)[-1] if "." in name else ""
    if ext not in ALLOWED_WORKSPACE_FILE_EXTENSIONS:
        raise ValueError(
            "File extension not allowed: "
            f"{ext}. Allowed: {sorted(ALLOWED_WORKSPACE_FILE_EXTENSIONS)}"
        )


def workspace_file_entry(root: Path, name: str) -> dict[str, Any]:
    """Build the wire entry for a supported agent workspace file."""

    path = root / name
    entry: dict[str, Any] = {
        "name": name,
        "path": name,
        "exists": False,
        "missing": True,
        "status": "missing",
    }
    try:
        file_stat = path.lstat()
    except FileNotFoundError:
        return entry
    entry.update({"exists": True, "missing": False})
    if stat.S_ISLNK(file_stat.st_mode):
        entry.update({"status": "unsafe", "unsafeReason": "symlink"})
        return entry
    if not stat.S_ISREG(file_stat.st_mode):
        entry.update({"status": "unsafe", "unsafeReason": "not-regular-file"})
        return entry
    if getattr(file_stat, "st_nlink", 1) > 1:
        entry.update({"status": "unsafe", "unsafeReason": "hardlink"})
        return entry
    entry.update({"status": "present", "size": file_stat.st_size})
    return entry


def list_workspace_agent_files(root: Path) -> list[dict[str, Any]]:
    """Build the wire payload rows for supported agent workspace files."""

    return [workspace_file_entry(root, name) for name in WORKSPACE_AGENT_FILE_NAMES]


def resolve_workspace_agent_file(root: Path, name: str) -> tuple[str, Path]:
    """Resolve a validated workspace file path without allowing root escape."""

    safe_name = validate_workspace_file_name(name)
    path = root / safe_name
    try:
        path.resolve(strict=False).relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError("workspace file escapes workspace root") from exc
    return safe_name, path


def validate_safe_file_stat(file_stat: os.stat_result) -> None:
    """Reject unsafe file types for agent workspace reads and writes."""

    if not stat.S_ISREG(file_stat.st_mode):
        raise ValueError("workspace agent file must be a regular file")
    if getattr(file_stat, "st_nlink", 1) > 1:
        raise ValueError("workspace agent file must not be hardlinked")


def read_workspace_agent_file(root: Path, name: str) -> tuple[str, str]:
    """Read a supported workspace file without following symlinks."""

    safe_name, path = resolve_workspace_agent_file(root, name)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, os.O_RDONLY | nofollow)
    except FileNotFoundError:
        raise
    except OSError as exc:
        raise ValueError("workspace agent file must not be a symlink") from exc

    try:
        validate_safe_file_stat(os.fstat(fd))
        with os.fdopen(fd, "r", encoding="utf-8") as handle:
            fd = -1
            content = handle.read()
    finally:
        if fd != -1:
            os.close(fd)
    return safe_name, content


def open_workspace_agent_file_for_write(path: Path) -> int:
    """Open a supported workspace file for overwrite without following symlinks."""

    nofollow = getattr(os, "O_NOFOLLOW", 0)
    try:
        file_stat = path.lstat()
    except FileNotFoundError:
        try:
            return os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow, 0o600)
        except FileExistsError:
            file_stat = path.lstat()
    if stat.S_ISLNK(file_stat.st_mode):
        raise ValueError("workspace agent file must not be a symlink")
    validate_safe_file_stat(file_stat)
    try:
        return os.open(path, os.O_WRONLY | nofollow)
    except OSError as exc:
        raise ValueError("workspace agent file must not be a symlink") from exc


def write_workspace_agent_file(root: Path, name: str, content: Any) -> dict[str, Any]:
    """Write a supported workspace file and return its wire payload."""

    validate_workspace_file_extension(name)
    safe_name, path = resolve_workspace_agent_file(root, name)
    text = content if isinstance(content, str) else str(content)
    data = text.encode("utf-8")
    fd = open_workspace_agent_file_for_write(path)
    try:
        validate_safe_file_stat(os.fstat(fd))
        os.ftruncate(fd, 0)
        os.write(fd, data)
    finally:
        os.close(fd)
    return {"name": safe_name, "path": safe_name, "size": len(data)}


__all__ = [
    "ALLOWED_WORKSPACE_FILE_EXTENSIONS",
    "WORKSPACE_AGENT_FILE_NAMES",
    "WORKSPACE_AGENT_FILE_NAME_SET",
    "list_workspace_agent_files",
    "open_workspace_agent_file_for_write",
    "read_workspace_agent_file",
    "resolve_workspace_agent_file",
    "validate_safe_file_stat",
    "validate_workspace_file_extension",
    "validate_workspace_file_name",
    "workspace_file_entry",
    "workspace_file_root_for_config",
    "write_workspace_agent_file",
]
