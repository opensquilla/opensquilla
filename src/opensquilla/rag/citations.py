"""Citation helpers for local document RAG."""

from __future__ import annotations

from .types import RagCitation, RagSearchResult

DEFAULT_COMPACT_PREVIEW_CHARS = 700


def citation_label(path: str) -> str:
    return f"[来源：{path}]"


def citation_to_wire(citation: RagCitation) -> dict[str, object]:
    return {
        "label": citation_label(citation.document_path),
        "collectionId": citation.collection_id,
        "sourceId": citation.source_id,
        "path": citation.document_path,
        "title": citation.document_title,
        "lineStart": citation.line_start,
        "lineEnd": citation.line_end,
        "page": citation.page,
    }


def result_to_wire(result: RagSearchResult, *, max_content_chars: int = 2000) -> dict[str, object]:
    content = result.content
    truncated = False
    if len(content) > max_content_chars:
        content = content[:max_content_chars].rstrip() + "\n..."
        truncated = True
    return {
        "chunkId": result.chunk_id,
        "documentId": result.document_id,
        "collectionId": result.collection_id,
        "sourceId": result.source_id,
        "path": result.document_path,
        "title": result.title,
        "content": content,
        "snippet": result.snippet,
        "score": result.score,
        "ftsScore": result.text_score or 0.0,
        "textScore": result.text_score,
        "vectorScore": result.vector_score,
        "retrievalMode": result.retrieval_mode,
        "sourceKind": result.source_kind,
        "sourceStatus": result.source_status,
        "untrustedEvidence": True,
        "citation": citation_to_wire(result.citation),
        "metadata": result.metadata,
        "truncated": truncated,
    }


def compact_result_to_wire(
    result: dict[str, object],
    *,
    max_preview_chars: int = DEFAULT_COMPACT_PREVIEW_CHARS,
) -> dict[str, object]:
    content = str(result.get("content") or result.get("snippet") or "")
    preview = content
    truncated = bool(result.get("truncated", False))
    if len(preview) > max_preview_chars:
        preview = preview[:max_preview_chars].rstrip() + "..."
        truncated = True
    metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
    score_breakdown = {}
    if isinstance(metadata, dict) and isinstance(metadata.get("scoreBreakdown"), dict):
        score_breakdown = dict(metadata["scoreBreakdown"])
    return {
        "chunkId": result.get("chunkId"),
        "documentId": result.get("documentId"),
        "collectionId": result.get("collectionId"),
        "sourceId": result.get("sourceId"),
        "path": result.get("path"),
        "title": result.get("title"),
        "snippet": result.get("snippet"),
        "contentPreview": preview,
        "score": result.get("score"),
        "ftsScore": result.get("ftsScore", result.get("textScore")),
        "textScore": result.get("textScore"),
        "vectorScore": result.get("vectorScore"),
        "scoreBreakdown": score_breakdown,
        "retrievalMode": result.get("retrievalMode"),
        "sourceKind": result.get("sourceKind", "rag"),
        "sourceStatus": result.get("sourceStatus"),
        "untrustedEvidence": True,
        "citation": result.get("citation"),
        "truncated": truncated,
    }
