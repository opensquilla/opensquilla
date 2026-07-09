"""Helpers for request-scoped workspace write deny rules."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path

from opensquilla.tools.types import SafeToolError, ToolContext, current_tool_context


@dataclass(frozen=True)
class WorkspaceWriteDenyMatch:
    pattern: str
    path: str
    resolved_path: str


@dataclass(frozen=True)
class WorkspaceScratchArtifactMatch:
    path: str
    resolved_path: str
    scratch_dir: str


_ROOT_DIAGNOSTIC_ARTIFACT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"^(?:debug|repro|reproduce|scratch|verify|inspect|investigate|trace|"
        r"analy[sz]e|analysis)(?:[_.-].*)?"
        r"\.(?:py|js|mjs|cjs|ts|rb|php|sh|txt|md|json|ya?ml|patch|diff|zsh)$",
        re.I,
    ),
    re.compile(
        r"^(?:check|fix|test)[_.-]"
        r"(?:bug|debug|failure|failing|issue|local|repro|scratch|temp|test|tmp|"
        r"verify|php|py|js|ts)(?:[_.-].*)?"
        r"\.(?:py|js|mjs|cjs|ts|rb|php|sh|txt|md|json|ya?ml|patch|diff|zsh)$",
        re.I,
    ),
)


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
    *,
    as_directory: bool = False,
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
    if as_directory:
        # A directory operand mutates everything beneath it; the trailing
        # slash lets dir/** style globs match the directory itself.
        candidates = [f"{candidate.rstrip('/')}/" for candidate in candidates]
    return tuple(dict.fromkeys(candidates))


def match_workspace_write_deny(
    path: Path,
    *,
    original_path: str | None = None,
    workspace: Path | None = None,
    ctx: ToolContext | None = None,
    as_directory: bool = False,
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
    if workspace is not None:
        try:
            resolved.relative_to(workspace)
        except ValueError:
            return None
    original = original_path if original_path is not None else str(path)
    candidates = _candidate_strings(resolved, original, workspace, as_directory=as_directory)

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


def match_workspace_scratch_artifact(
    path: Path,
    *,
    original_path: str | None = None,
    workspace: Path | None = None,
    ctx: ToolContext | None = None,
) -> WorkspaceScratchArtifactMatch | None:
    """Return a match for new root diagnostic artifacts that belong in scratch.

    The check is intentionally narrow: it only applies when a scratch directory
    is configured, only for new root-level files inside the workspace, and never
    for paths already under the scratch directory.
    """

    active = ctx if ctx is not None else current_tool_context.get()
    if active is None or not getattr(active, "scratch_dir", None):
        return None
    workspace = workspace if workspace is not None else _workspace_root(active)
    if workspace is None:
        return None
    resolved = path.expanduser().resolve(strict=False)
    scratch = Path(active.scratch_dir).expanduser().resolve(strict=False)  # type: ignore[arg-type]
    try:
        resolved.relative_to(scratch)
        return None
    except ValueError:
        pass
    try:
        relative = resolved.relative_to(workspace).as_posix()
    except ValueError:
        return None
    if "/" in relative or resolved.exists():
        return None
    if not any(pattern.match(relative) for pattern in _ROOT_DIAGNOSTIC_ARTIFACT_PATTERNS):
        return None
    original = original_path if original_path is not None else str(path)
    return WorkspaceScratchArtifactMatch(
        path=original,
        resolved_path=str(resolved),
        scratch_dir=str(scratch),
    )


def workspace_scratch_artifact_block(
    tool_name: str,
    match: WorkspaceScratchArtifactMatch,
    *,
    command: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "status": "blocked",
        "reason": "workspace_scratch_artifact",
        "tool": tool_name,
        "path": match.path,
        "resolved_path": match.resolved_path,
        "scratch_dir": match.scratch_dir,
        "message": (
            f"{tool_name} blocked creation of a temporary diagnostic artifact in "
            f"the workspace root: {match.path}. Temporary reproduction, debug, "
            "verification, or candidate-patch files must be written under the "
            f"configured scratch directory instead: {match.scratch_dir}."
        ),
        "retryable": True,
    }
    if command is not None:
        payload["command"] = command
        payload["target"] = match.path
    return payload


def gate_workspace_scratch_artifact(
    tool_name: str,
    path: Path,
    *,
    original_path: str | None = None,
    workspace: Path | None = None,
) -> None:
    match = match_workspace_scratch_artifact(
        path,
        original_path=original_path,
        workspace=workspace,
    )
    if match is None:
        return
    raise SafeToolError(str(workspace_scratch_artifact_block(tool_name, match)["message"]))


def workspace_write_deny_block(
    tool_name: str,
    match: WorkspaceWriteDenyMatch,
    *,
    command: str | None = None,
) -> dict[str, object]:
    guidance = _deny_retry_guidance()
    payload: dict[str, object] = {
        "status": "blocked",
        "reason": "workspace_write_deny",
        "tool": tool_name,
        "path": match.path,
        "resolved_path": match.resolved_path,
        "matched_pattern": match.pattern,
        "message": (
            f"{tool_name} blocked by workspace write deny policy: "
            f"{match.path} matches {match.pattern}.{guidance}"
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
    raise SafeToolError(str(workspace_write_deny_block(tool_name, match)["message"]))


def _deny_retry_guidance(ctx: ToolContext | None = None) -> str:
    # Opt-in override for the remediation sentence appended to deny messages.
    # The scratch-dir guidance below tells the model to recreate the file in
    # scratch, which is the wrong instruction when deny globs protect files
    # that must not be modified or copied at all (e.g. test files); deployments
    # using deny globs that way can supply intent-appropriate wording here.
    override = os.environ.get("OPENSQUILLA_WORKSPACE_WRITE_DENY_GUIDANCE", "").strip()
    if override:
        return f" {override}"
    return _scratch_retry_guidance(ctx)


def _scratch_retry_guidance(ctx: ToolContext | None = None) -> str:
    active = ctx if ctx is not None else current_tool_context.get()
    scratch_dir = getattr(active, "scratch_dir", None) if active is not None else None
    if not scratch_dir:
        return ""
    return (
        " Temporary reproduction, debug, verification, or candidate-patch files "
        f"must be written under the configured scratch directory instead: {scratch_dir}."
    )
