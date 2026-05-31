"""Helpers for request-scoped workspace write deny rules."""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path

from opensquilla.tools.types import ToolContext, ToolError, current_tool_context


@dataclass(frozen=True)
class WorkspaceWriteDenyMatch:
    pattern: str
    path: str
    resolved_path: str


def _workspace_write_deny_globs(ctx: ToolContext | None = None) -> tuple[str, ...]:
    active = ctx if ctx is not None else current_tool_context.get()
    if active is None:
        return ()
    patterns = getattr(active, "workspace_write_deny_globs", None) or []
    return tuple(str(pattern).strip() for pattern in patterns if str(pattern).strip())


def _workspace_root(ctx: ToolContext | None) -> Path | None:
    active = ctx if ctx is not None else current_tool_context.get()
    if active is None or not active.workspace_dir:
        return None
    return Path(active.workspace_dir).expanduser().resolve(strict=False)


def _candidate_strings(
    resolved: Path,
    original_path: str,
    workspace: Path | None,
) -> tuple[str, ...]:
    candidates: list[str] = [
        original_path.replace("\\", "/").lstrip("./"),
        resolved.as_posix(),
    ]
    if workspace is not None:
        try:
            relative = resolved.relative_to(workspace).as_posix()
        except ValueError:
            relative = ""
        if relative:
            candidates.extend([relative, f"./{relative}"])
    return tuple(dict.fromkeys(candidates))


def match_workspace_write_deny(
    path: Path,
    *,
    original_path: str | None = None,
    workspace: Path | None = None,
    ctx: ToolContext | None = None,
) -> WorkspaceWriteDenyMatch | None:
    """Return the deny rule matching a write target, if any.

    Patterns are opt-in and intentionally match both the original spelling and
    the active-workspace-relative path when a workspace is available.
    """

    patterns = _workspace_write_deny_globs(ctx)
    if not patterns:
        return None
    resolved = path.expanduser().resolve(strict=False)
    workspace = workspace if workspace is not None else _workspace_root(ctx)
    original = original_path if original_path is not None else str(path)
    candidates = _candidate_strings(resolved, original, workspace)

    for pattern in patterns:
        normalized_pattern = pattern.replace("\\", "/").lstrip("./")
        for candidate in candidates:
            normalized_candidate = candidate.replace("\\", "/").lstrip("./")
            if fnmatchcase(normalized_candidate, normalized_pattern) or fnmatchcase(
                f"/{normalized_candidate}", normalized_pattern
            ):
                return WorkspaceWriteDenyMatch(
                    pattern=pattern,
                    path=original,
                    resolved_path=str(resolved),
                )
    return None


def workspace_write_deny_block(
    tool_name: str,
    match: WorkspaceWriteDenyMatch,
    *,
    command: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "status": "blocked",
        "reason": "workspace_write_deny",
        "tool": tool_name,
        "path": match.path,
        "resolved_path": match.resolved_path,
        "matched_pattern": match.pattern,
        "message": (
            f"{tool_name} blocked by workspace write deny policy: "
            f"{match.path} matches {match.pattern}."
        ),
        "retryable": False,
    }
    if command is not None:
        payload["command"] = command
        payload["target"] = match.path
    return payload


def gate_workspace_write_deny(
    tool_name: str,
    path: Path,
    *,
    original_path: str | None = None,
    workspace: Path | None = None,
) -> None:
    match = match_workspace_write_deny(path, original_path=original_path, workspace=workspace)
    if match is None:
        return
    raise ToolError(
        f"{tool_name} blocked by workspace write deny policy: "
        f"{match.path} matches {match.pattern}."
    )
