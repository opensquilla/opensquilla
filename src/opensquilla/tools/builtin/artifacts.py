"""Explicit generated-artifact publication tool."""

from __future__ import annotations

import hashlib
import json
import mimetypes
from difflib import SequenceMatcher
from pathlib import Path

from opensquilla.artifacts import (
    DEFAULT_ARTIFACT_DISK_BUDGET_BYTES,
    DEFAULT_ARTIFACT_MAX_BYTES,
    ArtifactBudgetError,
    ArtifactStore,
    artifact_payload,
)
from opensquilla.tools.registry import tool
from opensquilla.tools.types import ToolError, current_tool_context

_MAX_MISSING_FILE_CANDIDATES = 5
_MAX_MISSING_FILE_SCAN = 2000


def _normalized_filename(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())


def _artifact_candidate_paths(
    workspace: Path,
    requested: Path,
    *,
    limit: int = _MAX_MISSING_FILE_CANDIDATES,
    max_scan: int = _MAX_MISSING_FILE_SCAN,
) -> list[str]:
    requested_name = requested.name
    if not requested_name:
        return []
    requested_norm = _normalized_filename(requested_name)
    requested_suffix = requested.suffix.lower()
    scored: list[tuple[float, str]] = []
    scanned = 0
    for candidate in workspace.rglob("*"):
        scanned += 1
        if scanned > max_scan:
            break
        if not candidate.is_file():
            continue
        candidate_name = candidate.name
        candidate_norm = _normalized_filename(candidate_name)
        score = 0.0
        if candidate_name == requested_name:
            score = 1.0
        elif candidate_name.lower() == requested_name.lower():
            score = 0.95
        elif requested_norm and candidate_norm == requested_norm:
            score = 0.9
        elif requested_suffix and candidate.suffix.lower() == requested_suffix:
            score = SequenceMatcher(None, requested_norm, candidate_norm).ratio()
        if score < 0.55:
            continue
        rel = candidate.relative_to(workspace).as_posix()
        scored.append((score, rel))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [path for _, path in scored[:limit]]


def _missing_artifact_error(path: str, workspace: Path, target: Path) -> ToolError:
    candidates = _artifact_candidate_paths(workspace, Path(path))
    details = [
        f"artifact file not found: {path}",
        f"active workspace: {workspace}",
        f"resolved path: {target}",
    ]
    if candidates:
        details.append("candidate files: " + ", ".join(candidates))
    else:
        details.append("candidate files: none found")
    return ToolError(". ".join(details))


@tool(
    name="publish_artifact",
    description=(
        "Publish an existing workspace file as a generated artifact for the user to download. "
        "Only files inside the active workspace are allowed. "
        "The user's UI shows a clickable download chip automatically; do not include any URL "
        "in your reply — just confirm the file is ready."
    ),
    params={
        "path": {
            "type": "string",
            "description": "Workspace-relative or in-workspace absolute path to publish.",
        },
        "name": {
            "type": "string",
            "description": "Optional download filename. Defaults to the source filename.",
        },
        "mime": {
            "type": "string",
            "description": "Optional MIME type. Defaults to a filename guess.",
        },
    },
    required=["path"],
)
async def publish_artifact(
    path: str,
    name: str | None = None,
    mime: str | None = None,
) -> str:
    ctx = current_tool_context.get()
    if ctx is None:
        raise ToolError("publish_artifact requires tool context")
    if not ctx.workspace_dir:
        raise ToolError("publish_artifact requires an active workspace")
    if not ctx.artifact_media_root:
        raise ToolError("artifact storage is not configured for this turn")
    if not ctx.artifact_session_id or not ctx.session_key:
        raise ToolError("artifact session scope is not configured for this turn")

    workspace = Path(ctx.workspace_dir).resolve()
    raw_path = Path(path)
    target = (raw_path if raw_path.is_absolute() else workspace / raw_path).resolve()
    try:
        target.relative_to(workspace)
    except ValueError as exc:
        raise ToolError(f"artifact path is outside workspace: {path}") from exc
    if not target.exists():
        raise _missing_artifact_error(path, workspace, target)
    if not target.is_file():
        raise ToolError(f"artifact path is not a file: {path}")

    target_sha256 = hashlib.sha256(target.read_bytes()).hexdigest()
    for published in reversed(ctx.published_artifacts):
        if published.get("sha256") != target_sha256:
            continue
        llm_artifact = {k: v for k, v in published.items() if k != "download_url"}
        return json.dumps(
            {
                "status": "already_published",
                "artifact": llm_artifact,
                "note": (
                    "This file is already published for the user in this turn. "
                    "Do not call publish_artifact again for the same file; "
                    "just confirm it is ready."
                ),
            },
            ensure_ascii=False,
        )

    artifact_mime = (mime or mimetypes.guess_type(name or target.name)[0] or "").strip()
    if not artifact_mime:
        artifact_mime = "application/octet-stream"

    store = ArtifactStore(ctx.artifact_media_root)
    try:
        ref = store.publish_file(
            target,
            session_id=ctx.artifact_session_id,
            session_key=ctx.session_key,
            name=name or target.name,
            mime=artifact_mime,
            source="publish_artifact",
            max_bytes=ctx.artifact_max_bytes
            if ctx.artifact_max_bytes is not None
            else DEFAULT_ARTIFACT_MAX_BYTES,
            disk_budget_bytes=ctx.artifact_disk_budget_bytes
            if ctx.artifact_disk_budget_bytes is not None
            else DEFAULT_ARTIFACT_DISK_BUDGET_BYTES,
        )
    except ArtifactBudgetError as exc:
        raise ToolError(str(exc)) from exc
    except FileNotFoundError as exc:
        if not target.exists():
            raise _missing_artifact_error(path, workspace, target) from exc
        raise ToolError(f"artifact storage path is unavailable: {exc}") from exc

    payload = artifact_payload(ref)
    ctx.published_artifacts.append(payload)
    llm_artifact = {k: v for k, v in payload.items() if k != "download_url"}
    return json.dumps(
        {
            "status": "published",
            "artifact": llm_artifact,
            "note": (
                "The user already sees a clickable download button rendered by the UI. "
                "Do not include any URL in your reply."
            ),
        },
        ensure_ascii=False,
    )
