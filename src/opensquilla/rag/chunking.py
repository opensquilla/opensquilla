"""Stable text chunking for local document RAG."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .parsers import ParsedDocument


@dataclass(slots=True)
class ChunkDraft:
    chunk_index: int
    content: str
    content_hash: str
    section: str | None
    line_start: int | None
    line_end: int | None


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _heading(line: str) -> str | None:
    stripped = line.strip()
    if not stripped.startswith("#"):
        return None
    prefix = len(stripped) - len(stripped.lstrip("#"))
    if 1 <= prefix <= 6 and len(stripped) > prefix and stripped[prefix] == " ":
        return stripped[prefix:].strip() or None
    return None


def chunk_document(
    document: ParsedDocument,
    *,
    chunk_size: int,
    chunk_overlap: int,
) -> list[ChunkDraft]:
    if chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be smaller than chunk_size")
    lines = document.text.splitlines(keepends=True)
    if not lines and document.text.strip():
        lines = [document.text]
    chunks: list[ChunkDraft] = []
    current: list[tuple[int, str, str | None]] = []
    current_len = 0
    section: str | None = None

    def emit() -> None:
        nonlocal current, current_len
        if not current:
            return
        content = "".join(line for _, line, _ in current).strip()
        if not content:
            current = []
            current_len = 0
            return
        line_start = current[0][0]
        line_end = current[-1][0]
        chunk_section = next((sec for _, _, sec in reversed(current) if sec), section)
        chunks.append(
            ChunkDraft(
                chunk_index=len(chunks),
                content=content,
                content_hash=_hash_text(content),
                section=chunk_section,
                line_start=line_start,
                line_end=line_end,
            )
        )
        if chunk_overlap <= 0:
            current = []
            current_len = 0
            return
        overlap: list[tuple[int, str, str | None]] = []
        overlap_len = 0
        for item in reversed(current):
            overlap.insert(0, item)
            overlap_len += len(item[1])
            if overlap_len >= chunk_overlap:
                break
        current = overlap
        current_len = overlap_len

    for line_no, line in enumerate(lines, start=1):
        heading = _heading(line)
        if heading:
            section = heading
            if current and current_len >= max(1, chunk_size // 2):
                emit()
        current.append((line_no, line, section))
        current_len += len(line)
        if current_len >= chunk_size:
            emit()
    emit()
    return chunks
