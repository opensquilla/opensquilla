"""Transactional memory writes used by the memory tool surface."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog

from opensquilla.memory.runtime import ResolvedMemoryAgent
from opensquilla.memory.source_paths import (
    is_memory_save_path,
    is_raw_fallback_save_path,
)

logger = structlog.get_logger(__name__)

_MEMORY_THREAT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.I),
    re.compile(r"you\s+are\s+now\s+(a|an)\b", re.I),
    re.compile(r"system\s+prompt\s+override", re.I),
    re.compile(r"new\s+instructions?\s*:", re.I),
    re.compile(r"(curl|wget)\s+.*\$\{?\w*(KEY|SECRET|TOKEN|PASSWORD)", re.I),
    re.compile(r"cat\s+.*(\.env|\.netrc|\.pgpass|credentials)", re.I),
    re.compile(r"authorized_keys", re.I),
    re.compile(r"<\s*system\s*>", re.I),
)

_INVISIBLE_CHARS = re.compile(r"[\u200b\u200c\u200d\ufeff\u202a-\u202e]")


class MemoryWriteError(RuntimeError):
    """Raised when a memory source write fails safely."""


@dataclass(frozen=True)
class PlannedMemoryWrite:
    path: str
    content: str
    mode: str


@dataclass(frozen=True)
class MemoryFileSnapshot:
    path: str
    abs_path: Path
    existed: bool
    content: str | None


def scan_memory_content(content: str) -> str | None:
    """Lightweight check for injection/exfiltration in memory content.

    Returns an error message if blocked, None if clean.
    """
    if _INVISIBLE_CHARS.search(content):
        return "Blocked: content contains invisible Unicode control characters."
    for pattern in _MEMORY_THREAT_PATTERNS:
        if pattern.search(content):
            return f"Blocked: content matches threat pattern ({pattern.pattern[:40]}...)."
    return None


async def prune_expired_files(
    memory_dir: str,
    store: Any,
    ttl_days: int,
    *,
    workspace_dir: str | None = None,
) -> None:
    """In-line TTL prune used by ``memory_save``.

    Thin back-compat wrapper around ``memory/retention.py``. Callers
    that hold a ``ResolvedMemoryAgent`` should pass ``workspace_dir`` so the
    helper builds store keys identical to the inline indexing path
    (``apply_memory_writes`` indexes ``plan.path`` which is
    workspace-relative). Defaults to ``memory_dir.parent`` for legacy
    direct calls. The background sweeper in ``MemorySyncManager`` covers
    paths the in-line call cannot reach (notably ``memory/archive/**``
    written by ``TurnCaptureService``).
    """
    from opensquilla.memory.retention import prune_expired_memory_files

    await prune_expired_memory_files(
        memory_dir=Path(memory_dir),
        store=store,
        ttl_days=ttl_days,
        workspace_dir=Path(workspace_dir) if workspace_dir else None,
    )


def validate_memory_save_target(path: str, mode: str) -> None:
    if not is_memory_save_path(path):
        raise MemoryWriteError(
            "invalid memory path. Use a memory source file: MEMORY.md or memory/**/*.md."
        )
    if path == "MEMORY.md" and mode != "replace":
        raise MemoryWriteError(
            "MEMORY.md must use mode='replace'. "
            "Read it first, then write the full updated content."
        )


async def apply_memory_writes(
    agent: ResolvedMemoryAgent,
    plans: list[PlannedMemoryWrite],
    *,
    memory_config: Any | None = None,
) -> dict[str, int]:
    from opensquilla.memory.types import MemorySource

    if not plans:
        return {}

    workspace_dir = _workspace_path(agent)
    await _maybe_prune(agent, memory_config)

    snapshots = _snapshot_paths(workspace_dir, plans)
    snapshot_map = {snapshot.path: snapshot for snapshot in snapshots}
    touched_paths: set[str] = set()
    chunks_by_path: dict[str, int] = {}

    try:
        for plan in plans:
            mem_path = snapshot_map[plan.path].abs_path
            _ensure_clean_memory_content(plan.content, plan.path)
            await _enforce_write_size_limits(
                agent,
                workspace_dir,
                mem_path,
                plan.content,
                plan.mode,
                memory_config,
            )
            _write_content(mem_path, plan.content, plan.mode)
            written_content = mem_path.read_text(encoding="utf-8")
            touched_paths.add(plan.path)
            if is_raw_fallback_save_path(plan.path):
                # Raw-dump fallback files live under ``memory/.raw_fallbacks/``
                # explicitly to escape retrieval. Skipping inline indexing
                # here matches the sync_manager dot-prefix exclusion so the
                # file never enters the store at write-time either.
                chunks_by_path[plan.path] = 0
            else:
                chunks_by_path[plan.path] = await agent.store.index_file(
                    path=plan.path,
                    content=written_content,
                    source=MemorySource.memory,
                )
        return chunks_by_path
    except Exception as exc:
        rollback_status = await _rollback_snapshots(agent, snapshots, touched_paths)
        if rollback_status == "no-op":
            raise
        _raise_with_rollback_context(exc, rollback_status)
        raise RuntimeError("unreachable")


def _workspace_path(agent: ResolvedMemoryAgent) -> Path:
    if not agent.workspace_dir:
        raise MemoryWriteError("workspace directory not configured.")
    return Path(agent.workspace_dir)


def _resolve_memory_path(workspace_dir: Path, path: str) -> Path:
    mem_path = workspace_dir / path
    try:
        mem_path.resolve().relative_to(workspace_dir.resolve())
    except ValueError as exc:
        raise MemoryWriteError("path traversal not allowed.") from exc
    return mem_path


def _ensure_clean_memory_content(content: str, path: str) -> None:
    threat = scan_memory_content(content)
    if threat:
        logger.warning("memory_save.blocked", path=path, reason=threat)
        raise MemoryWriteError(threat)


async def _maybe_prune(agent: ResolvedMemoryAgent, memory_config: Any | None) -> None:
    if memory_config and getattr(memory_config, "entry_ttl_days", 0) > 0 and agent.memory_dir:
        await prune_expired_files(
            agent.memory_dir,
            agent.store,
            memory_config.entry_ttl_days,
            workspace_dir=agent.workspace_dir,
        )


async def _enforce_write_size_limits(
    agent: ResolvedMemoryAgent,
    workspace_dir: Path,
    mem_path: Path,
    content: str,
    mode: str,
    memory_config: Any | None,
) -> None:
    if not memory_config:
        return

    content_size_kb = len(content.encode("utf-8")) / 1024

    max_file = getattr(memory_config, "max_file_size_kb", 0)
    if max_file > 0:
        existing_size = mem_path.stat().st_size / 1024 if mem_path.exists() else 0
        projected = (existing_size + content_size_kb) if mode != "replace" else content_size_kb
        if projected > max_file:
            raise MemoryWriteError(
                f"write would exceed per-file limit ({projected:.0f} KB > {max_file} KB)."
            )

    max_files = getattr(memory_config, "max_files", 0)
    if max_files > 0 and not mem_path.exists():
        file_count = len(list(workspace_dir.rglob("*.md")))
        if file_count >= max_files:
            raise MemoryWriteError(f"max file count reached ({max_files}).")

    max_total = getattr(memory_config, "max_total_size_kb", 0)
    if max_total > 0:
        total_kb = (await agent.store.total_size()) / 1024
        if total_kb + content_size_kb > max_total:
            raise MemoryWriteError(
                f"write would exceed total memory limit "
                f"({total_kb:.0f} + {content_size_kb:.0f} KB > {max_total} KB)."
            )


def _snapshot_paths(
    workspace_dir: Path,
    plans: list[PlannedMemoryWrite],
) -> list[MemoryFileSnapshot]:
    seen: set[str] = set()
    snapshots: list[MemoryFileSnapshot] = []
    for plan in plans:
        if plan.path in seen:
            continue
        seen.add(plan.path)
        abs_path = _resolve_memory_path(workspace_dir, plan.path)
        existed = abs_path.exists()
        content = abs_path.read_text(encoding="utf-8") if existed else None
        snapshots.append(
            MemoryFileSnapshot(
                path=plan.path,
                abs_path=abs_path,
                existed=existed,
                content=content,
            )
        )
    return snapshots


def _write_content(mem_path: Path, content: str, mode: str) -> None:
    mem_path.parent.mkdir(parents=True, exist_ok=True)
    if mode == "replace":
        mem_path.write_text(content, encoding="utf-8")
    elif mem_path.exists():
        with open(mem_path, "a", encoding="utf-8") as handle:
            handle.write("\n\n" + content)
    else:
        mem_path.write_text(content, encoding="utf-8")


async def _rollback_snapshots(
    agent: ResolvedMemoryAgent,
    snapshots: list[MemoryFileSnapshot],
    touched_paths: set[str],
) -> str:
    from opensquilla.memory.types import MemorySource

    if not touched_paths:
        return "no-op"

    statuses: list[str] = []
    for snapshot in snapshots:
        if snapshot.path not in touched_paths:
            continue
        try:
            if snapshot.existed:
                snapshot.abs_path.parent.mkdir(parents=True, exist_ok=True)
                snapshot.abs_path.write_text(snapshot.content or "", encoding="utf-8")
            elif snapshot.abs_path.exists():
                snapshot.abs_path.unlink()
        except Exception:
            statuses.append("disk_failed")
            continue

        try:
            if is_raw_fallback_save_path(snapshot.path):
                statuses.append("restored")
                continue
            if snapshot.existed:
                await agent.store.index_file(
                    path=snapshot.path,
                    content=snapshot.content or "",
                    source=MemorySource.memory,
                )
            else:
                await agent.store.remove_file(snapshot.path)
            statuses.append("restored")
        except Exception:
            statuses.append("index_stale")

    if any(status == "disk_failed" for status in statuses):
        return "disk_failed"
    if any(status == "index_stale" for status in statuses):
        return "index_stale"
    return "restored"


def _raise_with_rollback_context(exc: Exception, rollback_status: str) -> None:
    if rollback_status == "restored":
        suffix = "changes rolled back."
    elif rollback_status == "index_stale":
        suffix = "on-disk state rolled back, but index may be stale."
    elif rollback_status == "disk_failed":
        suffix = "rollback failed; disk and index may be inconsistent."
    else:
        suffix = "operation failed."

    message = f"{exc} ({suffix})"
    if isinstance(exc, MemoryWriteError):
        raise MemoryWriteError(message) from exc
    raise RuntimeError(message) from exc
