"""Runtime helpers for artifact delivery backstops."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from opensquilla.artifacts import (
    DEFAULT_ARTIFACT_DISK_BUDGET_BYTES,
    DEFAULT_ARTIFACT_MAX_BYTES,
    INSTALLER_ARTIFACT_SUFFIXES,
    ArtifactBudgetError,
    ArtifactStore,
    artifact_mime_for_name,
    artifact_payload,
    artifact_publish_max_bytes_for_name,
)
from opensquilla.tools.types import ToolContext

log = logging.getLogger(__name__)

_DELIVERABLE_SUFFIXES = frozenset(
    {
        ".csv",
        ".htm",
        ".html",
        ".json",
        ".pdf",
        ".pptx",
        ".tsv",
        ".xlsx",
        *INSTALLER_ARTIFACT_SUFFIXES,
    }
)
_EXCLUDED_TOP_LEVEL_DIRS = frozenset({".claude", ".codex", ".omx", "memory"})


@dataclass(frozen=True)
class OmittedArtifactPublishResult:
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    failure_summaries: list[str] = field(default_factory=list)


def _text_mentions_written_file(final_text: str, record: dict[str, Any]) -> bool:
    text = final_text.casefold()
    candidates = {
        str(record.get("relative_path") or ""),
        str(record.get("path") or ""),
        str(record.get("name") or ""),
    }
    return any(candidate and candidate.casefold() in text for candidate in candidates)


def _published_artifact_keys(ctx: ToolContext) -> set[tuple[str, str]]:
    return {
        (str(artifact.get("sha256")), str(artifact.get("name")))
        for artifact in ctx.published_artifacts
        if artifact.get("sha256") and artifact.get("name")
    }


def auto_publish_omitted_workspace_artifacts(
    ctx: ToolContext | None,
    *,
    final_text: str,
) -> OmittedArtifactPublishResult:
    """Publish deliverable files the model wrote but forgot to publish.

    This is intentionally conservative: a file must be written through a tracked
    workspace file tool during the current turn, have a deliverable suffix, and
    be named in the assistant's final text.
    """

    if ctx is None:
        return OmittedArtifactPublishResult()
    if not (
        ctx.workspace_dir
        and ctx.artifact_media_root
        and ctx.artifact_session_id
        and ctx.session_key
    ):
        return OmittedArtifactPublishResult()

    records = list(getattr(ctx, "workspace_file_writes", []) or [])
    if not records or not final_text.strip():
        return OmittedArtifactPublishResult()

    workspace = Path(ctx.workspace_dir).resolve()
    store = ArtifactStore(ctx.artifact_media_root)
    published: list[dict[str, Any]] = []
    failure_summaries: list[str] = []
    seen_paths: set[Path] = set()
    known_artifact_keys = _published_artifact_keys(ctx)

    for record in records:
        if not record.get("created"):
            # Publish only files created during this turn; edits to existing
            # files are tracked for diagnostics and are not deliverables.
            continue
        target = Path(str(record.get("path") or "")).expanduser().resolve(strict=False)
        if target in seen_paths:
            continue
        seen_paths.add(target)
        try:
            target.relative_to(workspace)
        except ValueError:
            continue
        relative_path = target.relative_to(workspace)
        if relative_path.parts and relative_path.parts[0] in _EXCLUDED_TOP_LEVEL_DIRS:
            continue
        if target.suffix.casefold() not in _DELIVERABLE_SUFFIXES:
            continue
        if not target.is_file():
            continue
        if not _text_mentions_written_file(final_text, record):
            continue

        try:
            target_sha256 = hashlib.sha256(target.read_bytes()).hexdigest()
            artifact_key = (target_sha256, target.name)
            if artifact_key in known_artifact_keys:
                continue
            artifact_mime = artifact_mime_for_name(target.name)
            existing = store.find_existing_ref(
                session_id=ctx.artifact_session_id,
                session_key=ctx.session_key,
                sha256=target_sha256,
                name=target.name,
                mime=artifact_mime,
            )
            if existing is None:
                ref = store.publish_file(
                    target,
                    session_id=ctx.artifact_session_id,
                    session_key=ctx.session_key,
                    name=target.name,
                    mime=artifact_mime,
                    source="auto_publish_omitted",
                    max_bytes=artifact_publish_max_bytes_for_name(
                        target.name,
                        ctx.artifact_max_bytes
                        if ctx.artifact_max_bytes is not None
                        else DEFAULT_ARTIFACT_MAX_BYTES,
                    ),
                    disk_budget_bytes=ctx.artifact_disk_budget_bytes
                    if ctx.artifact_disk_budget_bytes is not None
                    else DEFAULT_ARTIFACT_DISK_BUDGET_BYTES,
                )
            else:
                ref = existing
            payload = artifact_payload(ref)
            ctx.published_artifacts.append(payload)
            published.append(payload)
            known_artifact_keys.add(artifact_key)
        except (ArtifactBudgetError, OSError, ValueError) as exc:
            failure_summaries.append(f"auto-publish failed for {target.name}: {exc}")
            log.warning(
                "artifact_delivery.auto_publish_failed path=%s error=%s",
                str(target),
                exc,
            )
    return OmittedArtifactPublishResult(
        artifacts=published,
        failure_summaries=failure_summaries,
    )
