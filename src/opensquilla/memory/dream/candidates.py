"""Candidate scanning and lightweight signal classification for Dream."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from opensquilla.memory.dream.models import RawDreamCandidate
from opensquilla.memory.dream.quarantine import is_quarantined_path, is_quarantined_text

_SNIPPET_MAX_CHARS = 4000

# Marker that tags a line as one independent routing-preference claim. Mirrors
# ``preference_projection._MARKER_RE`` (the source of truth for the format); kept
# local so the Dream scanner takes no import edge on ``squilla_router``. A memory
# file whose every non-blank line carries this marker is an append-only preference
# log, so each line is scanned as its own candidate rather than collapsed into one.
_ROUTING_MARKER_RE = re.compile(r"`model:([A-Za-z0-9._:/@-]{1,200})`")


def _workspace_relative(workspace: Path, path: Path) -> str:
    try:
        return path.relative_to(workspace).as_posix()
    except ValueError:
        return path.as_posix()


def _normalize_snippet(text: str) -> str:
    return " ".join(text.strip().split())


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _source_day(path: Path) -> str | None:
    stem = path.stem
    if len(stem) >= 10 and stem[4:5] == "-" and stem[7:8] == "-":
        candidate = stem[:10]
        if all(part.isdigit() for part in candidate.split("-")):
            return candidate
    return None


def classify_signal(text: str) -> str:
    lowered = text.lower()
    if "memory:" in lowered or "remember that" in lowered:
        return "manual"
    if any(marker in lowered for marker in ("do not", "don't", "rejected", "wrong", "instead")):
        return "correction"
    if any(
        marker in lowered
        for marker in ("failed", "error", "exception", "traceback", "rollback")
    ):
        return "failure"
    if any(
        marker in lowered
        for marker in ("prefers", "accepted", "successful", "works", "use ")
    ):
        return "positive"
    return "neutral"


def _build_candidate(
    *,
    agent_id: str,
    rel_path: str,
    stat_mtime_ns: int,
    source_size: int,
    source_day: str | None,
    text: str,
    source_occurrence_id: str,
) -> RawDreamCandidate | None:
    snippet = _normalize_snippet(text)
    if len(snippet) > _SNIPPET_MAX_CHARS:
        snippet = snippet[:_SNIPPET_MAX_CHARS].rstrip()
    if not snippet:
        return None
    return RawDreamCandidate(
        agent_id=agent_id,
        source_path=rel_path,
        source_kind="memory_file",
        source_mtime_ns=stat_mtime_ns,
        source_size=source_size,
        snippet=snippet,
        snippet_sha256=_sha256(snippet),
        claim_sha256=_sha256(_normalize_snippet(snippet).lower()),
        source_day=source_day,
        signal_kind=classify_signal(snippet),
        source_occurrence_id=source_occurrence_id,
    )


def _split_units(raw: str) -> list[str]:
    """Yield the independent claim units of a memory file.

    An append-only preference log — every non-blank line carrying the routing
    marker — is split so each line is its own candidate (one thumb, one signal);
    otherwise the whole file is a single narrative candidate as before.
    """
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if lines and all(_ROUTING_MARKER_RE.search(line) for line in lines):
        return lines
    return [raw]


def scan_dream_candidates(
    workspace: Path,
    *,
    cursor: float,
    max_batch_size: int,
    agent_id: str,
    quarantine_enabled: bool = True,
) -> list[RawDreamCandidate]:
    memory_dir = workspace / "memory"
    if not memory_dir.exists():
        return []
    candidates: list[tuple[float, RawDreamCandidate]] = []
    for path in memory_dir.iterdir():
        try:
            if not path.is_file():
                continue
            stat = path.stat()
        except FileNotFoundError:
            continue
        if path.name.startswith(".") or path.name == "MEMORY.md" or path.suffix.lower() != ".md":
            continue
        if stat.st_mtime <= cursor:
            continue
        rel_path = _workspace_relative(workspace, path)
        if quarantine_enabled and is_quarantined_path(rel_path):
            continue
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if quarantine_enabled and is_quarantined_text(raw):
            continue
        source_day = _source_day(path)
        # The occurrence ordinal is scoped to equal normalized claims in one
        # source.  It is stable when new lines are appended, unlike a global
        # line number, and distinguishes repeated identical thumbs.
        occurrence_counts: dict[str, int] = {}
        for unit in _split_units(raw):
            normalized_unit = _normalize_snippet(unit).lower()
            occurrence_index = occurrence_counts.get(normalized_unit, 0)
            occurrence_counts[normalized_unit] = occurrence_index + 1
            source_occurrence_id = _sha256(
                "\n".join(
                    (
                        agent_id,
                        rel_path,
                        _sha256(normalized_unit),
                        str(occurrence_index),
                    )
                )
            )
            candidate = _build_candidate(
                agent_id=agent_id,
                rel_path=rel_path,
                stat_mtime_ns=stat.st_mtime_ns,
                source_size=stat.st_size,
                source_day=source_day,
                text=unit,
                source_occurrence_id=source_occurrence_id,
            )
            if candidate is None:
                continue
            candidates.append((stat.st_mtime, candidate))
    candidates.sort(
        key=lambda item: (
            item[0],
            item[1].source_path,
            item[1].snippet_sha256,
        )
    )
    limit = max(0, int(max_batch_size))
    if limit == 0 or not candidates:
        return []
    if len(candidates) <= limit:
        return [candidate for _mtime, candidate in candidates]

    # The persisted cursor contains only an mtime. Never split a timestamp tie
    # across batches: advancing to the first half's mtime would make the rest
    # fail the next scan's ``mtime > cursor`` check forever. The configured
    # limit is therefore soft at the boundary, which trades a bounded one-off
    # expansion for lossless progress on coarse-resolution filesystems.
    cutoff_mtime = candidates[limit - 1][0]
    return [
        candidate
        for mtime, candidate in candidates
        if mtime <= cutoff_mtime
    ]
