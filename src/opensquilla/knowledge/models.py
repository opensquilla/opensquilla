from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class KnowledgeDocument:
    doc_id: str
    title: str
    source: str
    source_path: str
    file_type: str
    content_kind: str
    date: str | None = None
    language_bucket: str = "mixed"
    pair_id: str | None = None
    content_sha256: str | None = None

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class KnowledgeChunk:
    chunk_id: str
    doc_id: str
    ordinal: int
    text: str
    title: str
    source: str
    source_path: str
    page_start: int | None = None
    page_end: int | None = None
    section: str | None = None
    language_bucket: str = "mixed"
    pair_id: str | None = None

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class KnowledgeSearchResult:
    evidence_id: str
    document_id: str
    chunk_id: str
    title: str
    source: str
    source_path: str
    page_start: int | None
    page_end: int | None
    section: str | None
    snippet: str
    score: float
    citation: str
    language_bucket: str
    pair_id: str | None = None
    rank_position: int = 0
    bm25_rank: float | None = None

    def to_wire(self) -> dict[str, Any]:
        return {
            "evidenceId": self.evidence_id,
            "documentId": self.document_id,
            "chunkId": self.chunk_id,
            "title": self.title,
            "source": self.source,
            "sourcePath": self.source_path,
            "pageStart": self.page_start,
            "pageEnd": self.page_end,
            "section": self.section,
            "snippet": self.snippet,
            "score": self.score,
            "citation": self.citation,
            "languageBucket": self.language_bucket,
            "pairId": self.pair_id,
            "rankPosition": self.rank_position,
            "bm25Rank": self.bm25_rank,
        }
