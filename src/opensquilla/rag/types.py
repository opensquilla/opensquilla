"""Domain types for local document RAG."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class RagSourceMode(StrEnum):
    REFERENCE = "reference"
    IMPORTED = "imported"


class RagSourceStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"
    MISSING = "missing"
    STALE = "stale"
    ERROR = "error"


class RagDocumentStatus(StrEnum):
    ACTIVE = "active"
    REMOVED = "removed"
    SKIPPED = "skipped"
    ERROR = "error"


class RagJobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELED = "canceled"


class RagRetrievalMode(StrEnum):
    HYBRID = "hybrid"
    FTS = "fts"
    VECTOR_ONLY = "vector_only"


class RagFallbackReason(StrEnum):
    NONE = "none"
    VECTOR_UNAVAILABLE = "vector_unavailable"
    EMBEDDING_UNAVAILABLE = "embedding_unavailable"
    SQLITE_VEC_UNAVAILABLE = "sqlite_vec_unavailable"
    EMPTY_VECTOR_INDEX = "empty_vector_index"
    VECTOR_INDEX_STALE = "vector_index_stale"


@dataclass(slots=True)
class RagCollection:
    collection_id: str
    name: str
    enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0
    updated_at: float = 0.0


@dataclass(slots=True)
class RagSource:
    source_id: str
    collection_id: str
    mode: RagSourceMode
    root_path: str
    display_name: str
    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    enabled: bool = True
    status: RagSourceStatus = RagSourceStatus.STALE
    stale_reason: str | None = None
    last_error: str | None = None
    last_scan_started_at: float | None = None
    last_scan_finished_at: float | None = None
    last_successful_scan_at: float | None = None
    last_indexed_at: float | None = None
    created_at: float = 0.0
    updated_at: float = 0.0


@dataclass(slots=True)
class RagDocument:
    document_id: str
    collection_id: str
    source_id: str
    relative_path: str
    absolute_path_snapshot: str
    title: str | None
    extension: str
    size_bytes: int
    mtime_ns: int
    content_hash: str | None
    parser: str | None
    status: RagDocumentStatus
    last_seen_scan_id: str | None = None
    indexed_at: float | None = None
    removed_at: float | None = None
    last_error: str | None = None
    created_at: float = 0.0
    updated_at: float = 0.0


@dataclass(slots=True)
class RagChunk:
    chunk_id: str
    document_id: str
    collection_id: str
    source_id: str
    relative_path: str
    chunk_index: int
    content: str
    content_hash: str
    title: str | None = None
    section: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    page: int | None = None
    token_count: int | None = None
    status: str = "active"
    created_at: float = 0.0
    updated_at: float = 0.0


@dataclass(slots=True)
class RagEmbedding:
    chunk_id: str
    provider: str
    model: str
    base_url: str | None
    dimensions: int
    fingerprint: str
    embedding: list[float]
    status: str = "active"


@dataclass(slots=True)
class RagCitation:
    collection_id: str
    source_id: str
    document_path: str
    document_title: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    page: int | None = None


@dataclass(slots=True)
class RagRawHit:
    chunk_id: str
    document_id: str
    collection_id: str
    source_id: str
    relative_path: str
    chunk_index: int
    content: str
    title: str | None
    line_start: int | None
    line_end: int | None
    source_status: str
    text_score: float | None = None
    vector_score: float | None = None


@dataclass(slots=True)
class RagSearchResult:
    chunk_id: str
    document_id: str
    collection_id: str
    source_id: str
    document_path: str
    title: str | None
    content: str
    snippet: str
    score: float
    text_score: float | None
    vector_score: float | None
    retrieval_mode: str
    source_kind: str
    source_status: str
    citation: RagCitation
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RagIndexJob:
    job_id: str
    job_type: str
    collection_id: str | None
    source_id: str | None
    status: RagJobStatus
    scan_id: str
    started_at: float
    finished_at: float | None = None
    files_seen: int = 0
    files_indexed: int = 0
    files_skipped: int = 0
    files_failed: int = 0
    chunks_written: int = 0
    embeddings_written: int = 0
    error_code: str | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RagSearchRequest:
    query: str
    mode: RagRetrievalMode | None = None
    limit: int | None = None
    min_score: float | None = None
    collection_id: str | None = None
    source_id: str | None = None
    path_prefix: str | None = None
