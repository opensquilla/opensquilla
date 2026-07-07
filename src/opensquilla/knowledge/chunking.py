from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from opensquilla.knowledge.models import KnowledgeChunk

_CJK_RE = re.compile(r"[\u3400-\u9fff]")
_LATIN_RE = re.compile(r"[A-Za-z]")
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*$")


def count_markdown_headings(text: str) -> int:
    return sum(1 for line in text.splitlines() if _HEADING_RE.match(line.strip()))


def chunker_candidates(text: str, *, suffix: str = "") -> list[str]:
    suffix = suffix.lower()
    candidates: list[str] = []
    if suffix in {".md", ".markdown"} or count_markdown_headings(text) > 0:
        candidates.append("markdown_heading_v1")
    candidates.append("paragraph_window_v1")
    candidates.append("sentence_window_v1")
    return candidates


def detect_language_bucket(text: str) -> str:
    cjk = len(_CJK_RE.findall(text))
    latin = len(_LATIN_RE.findall(text))
    if cjk and latin:
        return "mixed"
    if cjk:
        return "zh"
    if latin:
        return "en"
    return "mixed"


def extract_title(text: str, fallback: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        match = _HEADING_RE.match(stripped)
        if match:
            return match.group(1).strip()[:180]
        return stripped.lstrip("#").strip()[:180] or fallback
    return fallback


def _paragraphs(text: str) -> list[str]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    blocks = [block.strip() for block in re.split(r"\n\s*\n+", normalized) if block.strip()]
    if blocks:
        return blocks
    stripped = normalized.strip()
    return [stripped] if stripped else []


def _split_long_block(block: str, target_chars: int) -> Iterable[str]:
    if len(block) <= target_chars:
        yield block
        return
    sentences = re.split(r"(?<=[。！？.!?])\s*", block)
    current = ""
    for sentence in sentences:
        if not sentence:
            continue
        if current and len(current) + len(sentence) > target_chars:
            yield current.strip()
            current = sentence
        else:
            current += sentence
    if current.strip():
        yield current.strip()


def _trim_overlap(text: str, overlap_chars: int) -> str:
    if overlap_chars <= 0:
        return ""
    return text[-overlap_chars:].strip()


def chunk_text(
    text: str,
    *,
    doc_id: str,
    title: str,
    source_path: str,
    source: str,
    page_start: int | None = None,
    target_chars: int = 1200,
    overlap_chars: int = 120,
    pair_id: str | None = None,
    collection_id: str = "default",
    source_file_id: str | None = None,
    artifact_id: str | None = None,
    plan_id: str | None = None,
    strategy: str = "paragraph_window_v1",
    metadata: dict[str, Any] | None = None,
) -> list[KnowledgeChunk]:
    """Split one normalized document into citation-preserving chunks."""

    chunks: list[KnowledgeChunk] = []
    current = ""
    section: str | None = None

    def flush() -> None:
        nonlocal current
        body = current.strip()
        if not body:
            return
        ordinal = len(chunks)
        chunks.append(
            KnowledgeChunk(
                chunk_id=f"{doc_id}:{ordinal:04d}",
                doc_id=doc_id,
                ordinal=ordinal,
                text=body,
                title=title,
                source=source,
                source_path=source_path,
                page_start=page_start,
                page_end=page_start,
                section=section,
                language_bucket=detect_language_bucket(body),
                pair_id=pair_id,
                collection_id=collection_id,
                source_file_id=source_file_id,
                artifact_id=artifact_id,
                plan_id=plan_id,
                chunking_strategy=strategy,
                metadata=metadata or {},
            )
        )
        current = _trim_overlap(body, overlap_chars)

    for block in _paragraphs(text):
        heading = _HEADING_RE.match(block)
        if heading:
            section = heading.group(1).strip()
            if "\n" not in block:
                continue
        for piece in _split_long_block(block, target_chars):
            candidate = f"{current}\n\n{piece}".strip() if current else piece
            if current and len(candidate) > target_chars:
                flush()
                candidate = f"{current}\n\n{piece}".strip() if current else piece
            current = candidate
            if len(current) >= target_chars:
                flush()
    flush()
    return chunks
