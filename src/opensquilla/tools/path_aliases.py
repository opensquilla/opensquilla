"""Shared path aliases exposed by sandboxed tool runtimes."""

from __future__ import annotations

from pathlib import Path

_WORKSPACE_ALIAS = Path("/workspace")


def resolve_workspace_alias(raw_path: Path, workspace_root: Path | None) -> Path | None:
    """Map sandbox-visible /workspace paths back to the host workspace root."""

    if workspace_root is None:
        return None
    raw_text = raw_path.as_posix()
    if raw_text == "/workspace" or raw_text.startswith("/workspace/"):
        rel_text = raw_text.removeprefix("/workspace").lstrip("/")
        return (workspace_root / rel_text).resolve(strict=False)
    try:
        rel = raw_path.relative_to(_WORKSPACE_ALIAS)
    except ValueError:
        return None
    return (workspace_root / rel).resolve(strict=False)
