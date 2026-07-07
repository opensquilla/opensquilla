from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

JsonDict = dict[str, Any]


@dataclass(frozen=True)
class KnowledgeCollection:
    collection_id: str
    name: str
    description: str | None = None
    source_uri: str | None = None
    created_at: int | None = None
    updated_at: int | None = None
    config: JsonDict = field(default_factory=dict)

    def to_json(self) -> JsonDict:
        return asdict(self)


@dataclass(frozen=True)
class SourceSnapshot:
    snapshot_id: str
    collection_id: str
    source_uri: str
    snapshot_kind: str
    created_at: int
    metadata: JsonDict = field(default_factory=dict)

    def to_json(self) -> JsonDict:
        return asdict(self)


@dataclass(frozen=True)
class SourceFileRecord:
    source_file_id: str
    collection_id: str
    snapshot_id: str
    source_path: str
    absolute_path: str
    file_name: str
    extension: str
    size_bytes: int
    content_sha256: str
    status: str = "discovered"
    discovered_at: int | None = None
    metadata: JsonDict = field(default_factory=dict)

    def to_json(self) -> JsonDict:
        return asdict(self)


@dataclass(frozen=True)
class DocumentProfile:
    profile_id: str
    source_file_id: str
    collection_id: str
    mime_type: str
    encoding: str | None
    language_bucket: str
    text_quality: str
    structure_kind: str
    estimated_chars: int
    page_count: int | None = None
    has_frontmatter: bool = False
    heading_count: int = 0
    parser_candidates: list[str] = field(default_factory=list)
    chunker_candidates: list[str] = field(default_factory=list)
    metadata: JsonDict = field(default_factory=dict)

    def to_json(self) -> JsonDict:
        return asdict(self)


@dataclass(frozen=True)
class ProcessingPlan:
    plan_id: str
    source_file_id: str
    collection_id: str
    analyzer_version: str
    preprocessor_strategy: str
    chunking_strategy: str
    index_profiles: list[str]
    steps: list[JsonDict]
    status: str = "planned"
    created_at: int | None = None
    metadata: JsonDict = field(default_factory=dict)

    def to_json(self) -> JsonDict:
        return asdict(self)


@dataclass(frozen=True)
class ArtifactRecord:
    artifact_id: str
    collection_id: str
    source_file_id: str
    document_id: str | None
    artifact_type: str
    strategy: str
    uri: str
    content_sha256: str
    size_bytes: int
    created_at: int
    metadata: JsonDict = field(default_factory=dict)

    def to_json(self) -> JsonDict:
        return asdict(self)


@dataclass(frozen=True)
class ChunkLineage:
    lineage_id: str
    chunk_id: str
    document_id: str
    source_file_id: str
    collection_id: str
    artifact_id: str | None
    plan_id: str
    step_ordinal: int
    operation: str
    params: JsonDict
    input_ref: str | None
    output_ref: str | None
    reversible: bool
    created_at: int

    def to_json(self) -> JsonDict:
        return asdict(self)


@dataclass(frozen=True)
class IndexBuildRecord:
    build_id: str
    collection_id: str
    profile_id: str
    index_type: str
    status: str
    documents_indexed: int
    chunks_indexed: int
    created_at: int
    completed_at: int | None = None
    metadata: JsonDict = field(default_factory=dict)

    def to_json(self) -> JsonDict:
        return asdict(self)


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
    collection_id: str = "default"
    source_file_id: str | None = None
    profile_id: str | None = None
    plan_id: str | None = None
    parser: str | None = None
    metadata: JsonDict = field(default_factory=dict)

    def to_json(self) -> JsonDict:
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
    collection_id: str = "default"
    source_file_id: str | None = None
    artifact_id: str | None = None
    plan_id: str | None = None
    chunking_strategy: str | None = None
    char_start: int | None = None
    char_end: int | None = None
    metadata: JsonDict = field(default_factory=dict)

    def to_json(self) -> JsonDict:
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
    collection_id: str = "default"
    retrieval_profile: str = "sqlite_fts5_default"
    chunking_strategy: str | None = None

    def to_wire(self) -> JsonDict:
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
            "collectionId": self.collection_id,
            "retrievalProfile": self.retrieval_profile,
            "chunkingStrategy": self.chunking_strategy,
        }
