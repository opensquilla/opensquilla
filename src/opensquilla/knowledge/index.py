from __future__ import annotations

import json
import re
import sqlite3
import time
from collections.abc import Sequence
from hashlib import sha256
from pathlib import Path
from typing import Any

from opensquilla.knowledge.models import (
    ArtifactRecord,
    ChunkLineage,
    DocumentProfile,
    IndexBuildRecord,
    KnowledgeChunk,
    KnowledgeCollection,
    KnowledgeDocument,
    KnowledgeSearchResult,
    ProcessingPlan,
    SourceFileRecord,
    SourceSnapshot,
)
from opensquilla.knowledge.pipeline import make_stable_id
from opensquilla.knowledge.schema import ensure_schema

_CJK_RE = re.compile(r"[\u3400-\u9fff]")
_WORD_RE = re.compile(r"[A-Za-z0-9_]{2,}")
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


def _cjk_ngrams(text: str) -> list[str]:
    chars = _CJK_RE.findall(text)
    grams: list[str] = []
    for size in (2, 3):
        grams.extend("".join(chars[i : i + size]) for i in range(max(0, len(chars) - size + 1)))
    return grams[:3000]


def _search_text(*values: str | None) -> str:
    raw = "\n".join(value for value in values if value)
    return f"{raw}\n{' '.join(_cjk_ngrams(raw))}"


def _query_terms(query: str) -> list[str]:
    terms = _WORD_RE.findall(query)
    cjk = _CJK_RE.findall(query)
    terms.extend(
        "".join(cjk[i : i + size])
        for size in (2, 3)
        for i in range(max(0, len(cjk) - size + 1))
    )
    seen: set[str] = set()
    result: list[str] = []
    for term in terms:
        normalized = term.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _fts_query(query: str) -> str:
    terms = _query_terms(query)
    if not terms:
        return ""
    escaped = [term.replace('"', '""') for term in terms[:16]]
    return " OR ".join(f'"{term}"' for term in escaped)


def _snippet(text: str, query: str, budget: int = 420) -> str:
    stripped = " ".join(text.split())
    if len(stripped) <= budget:
        return stripped
    lowered = stripped.lower()
    positions = [
        lowered.find(term.lower()) for term in _query_terms(query) if term.lower() in lowered
    ]
    center = min((pos for pos in positions if pos >= 0), default=0)
    start = max(0, center - budget // 3)
    end = min(len(stripped), start + budget)
    start = max(0, end - budget)
    prefix = "... " if start else ""
    suffix = " ..." if end < len(stripped) else ""
    return f"{prefix}{stripped[start:end].strip()}{suffix}"


def _citation(source_path: str, page_start: int | None) -> str:
    return f"{source_path}#page={page_start}" if page_start else source_path


def _dedupe_key(text: str) -> str:
    normalized = _HTML_COMMENT_RE.sub("", text)
    normalized = " ".join(normalized.split())
    return sha256(normalized.encode("utf-8")).hexdigest()


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, sort_keys=True)


def _json_list(value: Any) -> str:
    return json.dumps(value if value is not None else [], ensure_ascii=False)


def _loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


class KnowledgeIndex:
    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            ensure_schema(conn)

    def reset(self) -> None:
        self.initialize()
        with self._connect() as conn:
            self._delete_all(conn)

    def reset_collection(self, collection_id: str = "default") -> None:
        self.initialize()
        with self._connect() as conn:
            self._delete_collection(conn, collection_id)

    def replace_collection_records(
        self,
        *,
        collection: KnowledgeCollection,
        snapshot: SourceSnapshot,
        source_files: Sequence[SourceFileRecord],
        profiles: Sequence[DocumentProfile],
        plans: Sequence[ProcessingPlan],
        artifacts: Sequence[ArtifactRecord],
        documents: Sequence[KnowledgeDocument],
        chunks: Sequence[KnowledgeChunk],
        lineages: Sequence[ChunkLineage],
        manifest_entries: Sequence[dict[str, Any]],
        ingest_job: dict[str, Any],
        index_builds: Sequence[IndexBuildRecord],
    ) -> None:
        self.initialize()
        with self._connect() as conn:
            self._delete_collection(conn, collection.collection_id)
            self._upsert_collection(conn, collection)
            self._upsert_snapshot(conn, snapshot)
            self._upsert_source_files(conn, source_files)
            self._upsert_profiles(conn, profiles)
            self._upsert_plans(conn, plans)
            self._upsert_documents(conn, documents)
            self._upsert_artifacts(conn, artifacts)
            self._upsert_chunks(conn, chunks)
            self._upsert_lineage(conn, lineages)
            self._upsert_manifest_entries(conn, manifest_entries)
            self._upsert_index_builds(conn, index_builds)
            self._upsert_ingest_job(conn, ingest_job)
            self._rebuild_fts(conn, collection.collection_id, chunks)

    def add_documents(
        self,
        documents: Sequence[KnowledgeDocument],
        chunks: Sequence[KnowledgeChunk],
    ) -> None:
        self.initialize()
        now = int(time.time() * 1000)
        collection_ids = {doc.collection_id or "default" for doc in documents} or {"default"}
        with self._connect() as conn:
            for collection_id in collection_ids:
                collection = KnowledgeCollection(
                    collection_id=collection_id,
                    name=collection_id,
                    created_at=now,
                    updated_at=now,
                    config={"legacyAddDocuments": True},
                )
                snapshot = SourceSnapshot(
                    snapshot_id=make_stable_id("snap", collection_id, "legacy"),
                    collection_id=collection_id,
                    source_uri="legacy:add_documents",
                    snapshot_kind="legacy",
                    created_at=now,
                )
                self._upsert_collection(conn, collection)
                self._upsert_snapshot(conn, snapshot)
                source_files = [
                    _legacy_source_file(doc, snapshot.snapshot_id, now)
                    for doc in documents
                    if (doc.collection_id or "default") == collection_id
                ]
                self._upsert_source_files(conn, source_files)
            normalized_documents = [_normalize_doc(doc) for doc in documents]
            source_file_by_doc = {
                doc.doc_id: doc.source_file_id
                or make_stable_id("sf", doc.collection_id, doc.source_path, doc.doc_id)
                for doc in normalized_documents
            }
            normalized_chunks = [
                _normalize_chunk(chunk, source_file_by_doc.get(chunk.doc_id))
                for chunk in chunks
            ]
            self._upsert_documents(conn, normalized_documents)
            self._upsert_chunks(conn, normalized_chunks)
            for collection_id in collection_ids:
                self._rebuild_fts(
                    conn,
                    collection_id,
                    [
                        chunk
                        for chunk in normalized_chunks
                        if (chunk.collection_id or "default") == collection_id
                    ],
                )

    def search(
        self,
        query: str,
        *,
        top_k: int = 8,
        filters: dict[str, Any] | None = None,
    ) -> list[KnowledgeSearchResult]:
        self.initialize()
        clean_query = query.strip()
        if not clean_query:
            return []
        limit = max(1, min(int(top_k or 8), 20))
        candidate_limit = min(max(limit * 5, limit), 100)
        fts_query = _fts_query(clean_query)
        filters = filters or {}
        retrieval_profile = str(filters.get("retrievalProfile") or "sqlite_fts5_default")
        collection_id = str(filters.get("collectionId") or filters.get("collection") or "default")

        where = ["c.collection_id = ?"]
        params: list[Any] = [collection_id]
        if source := filters.get("source"):
            where.append("c.source = ?")
            params.append(str(source))
        if content_kind := filters.get("contentKind"):
            where.append("d.content_kind = ?")
            params.append(str(content_kind))
        where_sql = " AND ".join(where)

        with self._connect() as conn:
            rows: list[sqlite3.Row]
            if fts_query:
                rows = conn.execute(
                    f"""
                    SELECT c.*, d.content_kind, bm25(fts_chunks) AS rank
                    FROM fts_chunks
                    JOIN chunks c ON c.chunk_id = fts_chunks.chunk_id
                    JOIN documents d ON d.document_id = c.document_id
                    WHERE fts_chunks MATCH ?
                      AND {where_sql}
                    ORDER BY rank ASC
                    LIMIT ?
                    """,
                    [fts_query, *params, candidate_limit],
                ).fetchall()
            else:
                rows = []
            if not rows:
                like = f"%{clean_query}%"
                rows = conn.execute(
                    f"""
                    SELECT c.*, d.content_kind, 0.0 AS rank
                    FROM chunks c
                    JOIN documents d ON d.document_id = c.document_id
                    WHERE c.text LIKE ?
                      AND {where_sql}
                    ORDER BY c.ordinal ASC
                    LIMIT ?
                    """,
                    [like, *params, candidate_limit],
                ).fetchall()

        results: list[KnowledgeSearchResult] = []
        seen_text: set[str] = set()
        for row in rows:
            text = str(row["text"])
            dedupe_key = _dedupe_key(text)
            if dedupe_key in seen_text:
                continue
            seen_text.add(dedupe_key)
            rank = float(row["rank"] or 0.0)
            score = round(max(-rank, 0.0), 4)
            position = len(results) + 1
            results.append(
                KnowledgeSearchResult(
                    evidence_id=f"ev_{position:03d}",
                    document_id=str(row["document_id"]),
                    chunk_id=str(row["chunk_id"]),
                    title=str(row["title"]),
                    source=str(row["source"]),
                    source_path=str(row["source_path"]),
                    page_start=row["page_start"],
                    page_end=row["page_end"],
                    section=row["section"],
                    snippet=_snippet(text, clean_query),
                    score=score,
                    citation=_citation(str(row["source_path"]), row["page_start"]),
                    language_bucket=str(row["language_bucket"]),
                    pair_id=row["pair_id"],
                    rank_position=position,
                    bm25_rank=round(rank, 6),
                    collection_id=str(row["collection_id"]),
                    retrieval_profile=retrieval_profile,
                    chunking_strategy=row["chunking_strategy"],
                )
            )
            if len(results) >= limit:
                break
        return results

    def get(
        self,
        *,
        chunk_id: str | None = None,
        document_id: str | None = None,
    ) -> dict[str, Any] | None:
        self.initialize()
        if not chunk_id and not document_id:
            raise ValueError("chunk_id or document_id is required")
        with self._connect() as conn:
            if chunk_id:
                row = conn.execute(
                    """
                    SELECT c.*, d.content_kind, d.date, d.parser, d.profile_id, d.plan_id,
                           p.preprocessor_strategy, p.chunking_strategy AS planned_chunking_strategy
                    FROM chunks c
                    JOIN documents d ON d.document_id = c.document_id
                    LEFT JOIN processing_plans p ON p.plan_id = c.plan_id
                    WHERE c.chunk_id = ?
                    """,
                    (chunk_id,),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT c.*, d.content_kind, d.date, d.parser, d.profile_id, d.plan_id,
                           p.preprocessor_strategy, p.chunking_strategy AS planned_chunking_strategy
                    FROM chunks c
                    JOIN documents d ON d.document_id = c.document_id
                    LEFT JOIN processing_plans p ON p.plan_id = c.plan_id
                    WHERE c.document_id = ?
                    ORDER BY c.ordinal ASC
                    LIMIT 1
                    """,
                    (document_id,),
                ).fetchone()
            if row is None:
                return None
            lineage = conn.execute(
                """
                SELECT step_ordinal, operation, params_json, input_ref, output_ref, reversible
                FROM chunk_lineage
                WHERE chunk_id = ?
                ORDER BY step_ordinal ASC
                """,
                (row["chunk_id"],),
            ).fetchall()
        return {
            "chunkId": row["chunk_id"],
            "documentId": row["document_id"],
            "collectionId": row["collection_id"],
            "ordinal": row["ordinal"],
            "text": row["text"],
            "title": row["title"],
            "source": row["source"],
            "sourcePath": row["source_path"],
            "pageStart": row["page_start"],
            "pageEnd": row["page_end"],
            "section": row["section"],
            "languageBucket": row["language_bucket"],
            "pairId": row["pair_id"],
            "citation": _citation(row["source_path"], row["page_start"]),
            "contentKind": row["content_kind"],
            "date": row["date"],
            "parser": row["parser"],
            "profileId": row["profile_id"],
            "planId": row["plan_id"],
            "preprocessorStrategy": row["preprocessor_strategy"],
            "chunkingStrategy": row["chunking_strategy"] or row["planned_chunking_strategy"],
            "charStart": row["char_start"],
            "charEnd": row["char_end"],
            "metadata": _loads(row["metadata_json"], {}),
            "lineage": [
                {
                    "stepOrdinal": item["step_ordinal"],
                    "operation": item["operation"],
                    "params": _loads(item["params_json"], {}),
                    "inputRef": item["input_ref"],
                    "outputRef": item["output_ref"],
                    "reversible": bool(item["reversible"]),
                }
                for item in lineage
            ],
        }

    def stats(self) -> dict[str, Any]:
        self.initialize()
        with self._connect() as conn:
            docs = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
            files = conn.execute("SELECT COUNT(*) FROM source_files").fetchone()[0]
            collections = conn.execute("SELECT COUNT(*) FROM collections").fetchone()[0]
            sources = conn.execute(
                """
                SELECT source, COUNT(*) AS count
                FROM documents
                GROUP BY source
                ORDER BY count DESC, source ASC
                LIMIT 20
                """
            ).fetchall()
            latest_job = conn.execute(
                """
                SELECT *
                FROM ingest_jobs
                ORDER BY started_at DESC
                LIMIT 1
                """
            ).fetchone()
        payload: dict[str, Any] = {
            "documentsIndexed": int(docs),
            "chunksIndexed": int(chunks),
            "filesIndexed": int(files),
            "collections": int(collections),
            "sources": [{"source": row["source"], "count": int(row["count"])} for row in sources],
            "dbPath": str(self.db_path),
            "indexProfiles": ["sqlite_fts5_default"],
        }
        if latest_job is not None:
            payload["latestJob"] = _job_to_wire(latest_job)
        return payload

    def list_collections(self) -> list[dict[str, Any]]:
        self.initialize()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT c.*,
                       COUNT(DISTINCT d.document_id) AS documents_indexed,
                       COUNT(DISTINCT ch.chunk_id) AS chunks_indexed
                FROM collections c
                LEFT JOIN documents d ON d.collection_id = c.collection_id
                LEFT JOIN chunks ch ON ch.collection_id = c.collection_id
                GROUP BY c.collection_id
                ORDER BY c.updated_at DESC
                """
            ).fetchall()
        return [
            {
                "collectionId": row["collection_id"],
                "name": row["name"],
                "description": row["description"],
                "sourceUri": row["source_uri"],
                "createdAt": row["created_at"],
                "updatedAt": row["updated_at"],
                "documentsIndexed": int(row["documents_indexed"]),
                "chunksIndexed": int(row["chunks_indexed"]),
                "config": _loads(row["config_json"], {}),
            }
            for row in rows
        ]

    def record_judgment(self, payload: dict[str, Any]) -> None:
        self.initialize()
        created_at = int(payload.get("createdAt") or time.time() * 1000)
        judgment_id = make_stable_id(
            "judg",
            str(payload.get("collectionId") or "default"),
            str(payload.get("questionId") or ""),
            str(created_at),
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO judgments (
                    judgment_id, collection_id, question_id, question, rating, evidence,
                    hallucination, notes, selected_chunk_id, results_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    judgment_id,
                    payload.get("collectionId") or "default",
                    str(payload.get("questionId") or ""),
                    str(payload.get("question") or ""),
                    str(payload.get("rating") or ""),
                    str(payload.get("evidence") or ""),
                    str(payload.get("hallucination") or ""),
                    str(payload.get("notes") or ""),
                    payload.get("selectedChunkId"),
                    _json_list(payload.get("results") or []),
                    created_at,
                ),
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _delete_all(self, conn: sqlite3.Connection) -> None:
        conn.execute("DELETE FROM fts_chunks")
        for table in (
            "chunk_lineage",
            "chunks",
            "artifacts",
            "documents",
            "processing_plans",
            "document_profiles",
            "manifest_entries",
            "metadata_kv",
            "index_catalog",
            "index_builds",
            "ingest_jobs",
            "judgments",
            "source_files",
            "source_snapshots",
            "collections",
        ):
            conn.execute(f"DELETE FROM {table}")

    def _delete_collection(self, conn: sqlite3.Connection, collection_id: str) -> None:
        conn.execute("DELETE FROM fts_chunks WHERE collection_id = ?", (collection_id,))
        for table in (
            "chunk_lineage",
            "chunks",
            "artifacts",
            "documents",
            "processing_plans",
            "document_profiles",
            "manifest_entries",
            "index_catalog",
            "index_builds",
            "ingest_jobs",
            "source_files",
            "source_snapshots",
        ):
            conn.execute(f"DELETE FROM {table} WHERE collection_id = ?", (collection_id,))
        conn.execute("DELETE FROM collections WHERE collection_id = ?", (collection_id,))

    def _upsert_collection(self, conn: sqlite3.Connection, collection: KnowledgeCollection) -> None:
        now = int(time.time() * 1000)
        conn.execute(
            """
            INSERT OR REPLACE INTO collections (
                collection_id, name, description, source_uri, created_at, updated_at, config_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                collection.collection_id,
                collection.name,
                collection.description,
                collection.source_uri,
                collection.created_at or now,
                collection.updated_at or now,
                _json(collection.config),
            ),
        )

    def _upsert_snapshot(self, conn: sqlite3.Connection, snapshot: SourceSnapshot) -> None:
        conn.execute(
            """
            INSERT OR REPLACE INTO source_snapshots (
                snapshot_id, collection_id, source_uri, snapshot_kind, created_at, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot.snapshot_id,
                snapshot.collection_id,
                snapshot.source_uri,
                snapshot.snapshot_kind,
                snapshot.created_at,
                _json(snapshot.metadata),
            ),
        )

    def _upsert_source_files(
        self,
        conn: sqlite3.Connection,
        source_files: Sequence[SourceFileRecord],
    ) -> None:
        conn.executemany(
            """
            INSERT OR REPLACE INTO source_files (
                source_file_id, collection_id, snapshot_id, source_path, absolute_path,
                file_name, extension, size_bytes, content_sha256, status, discovered_at,
                metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    item.source_file_id,
                    item.collection_id,
                    item.snapshot_id,
                    item.source_path,
                    item.absolute_path,
                    item.file_name,
                    item.extension,
                    item.size_bytes,
                    item.content_sha256,
                    item.status,
                    item.discovered_at or int(time.time() * 1000),
                    _json(item.metadata),
                )
                for item in source_files
            ],
        )

    def _upsert_profiles(
        self,
        conn: sqlite3.Connection,
        profiles: Sequence[DocumentProfile],
    ) -> None:
        conn.executemany(
            """
            INSERT OR REPLACE INTO document_profiles (
                profile_id, source_file_id, collection_id, mime_type, encoding,
                language_bucket, text_quality, structure_kind, estimated_chars, page_count,
                has_frontmatter, heading_count, parser_candidates_json, chunker_candidates_json,
                metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    item.profile_id,
                    item.source_file_id,
                    item.collection_id,
                    item.mime_type,
                    item.encoding,
                    item.language_bucket,
                    item.text_quality,
                    item.structure_kind,
                    item.estimated_chars,
                    item.page_count,
                    1 if item.has_frontmatter else 0,
                    item.heading_count,
                    _json_list(item.parser_candidates),
                    _json_list(item.chunker_candidates),
                    _json(item.metadata),
                    int(time.time() * 1000),
                )
                for item in profiles
            ],
        )

    def _upsert_plans(self, conn: sqlite3.Connection, plans: Sequence[ProcessingPlan]) -> None:
        conn.executemany(
            """
            INSERT OR REPLACE INTO processing_plans (
                plan_id, source_file_id, collection_id, analyzer_version,
                preprocessor_strategy, chunking_strategy, index_profiles_json,
                steps_json, status, metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    item.plan_id,
                    item.source_file_id,
                    item.collection_id,
                    item.analyzer_version,
                    item.preprocessor_strategy,
                    item.chunking_strategy,
                    _json_list(item.index_profiles),
                    _json_list(item.steps),
                    item.status,
                    _json(item.metadata),
                    item.created_at or int(time.time() * 1000),
                )
                for item in plans
            ],
        )

    def _upsert_documents(
        self,
        conn: sqlite3.Connection,
        documents: Sequence[KnowledgeDocument],
    ) -> None:
        now = int(time.time() * 1000)
        conn.executemany(
            """
            INSERT OR REPLACE INTO documents (
                document_id, collection_id, source_file_id, title, source, source_path,
                file_type, content_kind, date, language_bucket, pair_id, content_sha256,
                profile_id, plan_id, parser, metadata_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    item.doc_id,
                    item.collection_id,
                    item.source_file_id
                    or make_stable_id("sf", item.collection_id, item.source_path, item.doc_id),
                    item.title,
                    item.source,
                    item.source_path,
                    item.file_type,
                    item.content_kind,
                    item.date,
                    item.language_bucket,
                    item.pair_id,
                    item.content_sha256,
                    item.profile_id,
                    item.plan_id,
                    item.parser,
                    _json(item.metadata),
                    now,
                    now,
                )
                for item in documents
            ],
        )

    def _upsert_artifacts(
        self,
        conn: sqlite3.Connection,
        artifacts: Sequence[ArtifactRecord],
    ) -> None:
        conn.executemany(
            """
            INSERT OR REPLACE INTO artifacts (
                artifact_id, collection_id, source_file_id, document_id, artifact_type,
                strategy, uri, content_sha256, size_bytes, metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    item.artifact_id,
                    item.collection_id,
                    item.source_file_id,
                    item.document_id,
                    item.artifact_type,
                    item.strategy,
                    item.uri,
                    item.content_sha256,
                    item.size_bytes,
                    _json(item.metadata),
                    item.created_at,
                )
                for item in artifacts
            ],
        )

    def _upsert_chunks(self, conn: sqlite3.Connection, chunks: Sequence[KnowledgeChunk]) -> None:
        now = int(time.time() * 1000)
        conn.executemany(
            """
            INSERT OR REPLACE INTO chunks (
                chunk_id, document_id, collection_id, source_file_id, artifact_id, plan_id,
                ordinal, text, title, source, source_path, page_start, page_end, section,
                language_bucket, pair_id, chunking_strategy, char_start, char_end,
                metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    item.chunk_id,
                    item.doc_id,
                    item.collection_id,
                    item.source_file_id
                    or make_stable_id("sf", item.collection_id, item.source_path, item.doc_id),
                    item.artifact_id,
                    item.plan_id,
                    item.ordinal,
                    item.text,
                    item.title,
                    item.source,
                    item.source_path,
                    item.page_start,
                    item.page_end,
                    item.section,
                    item.language_bucket,
                    item.pair_id,
                    item.chunking_strategy,
                    item.char_start,
                    item.char_end,
                    _json(item.metadata),
                    now,
                )
                for item in chunks
            ],
        )

    def _upsert_lineage(
        self,
        conn: sqlite3.Connection,
        lineages: Sequence[ChunkLineage],
    ) -> None:
        conn.executemany(
            """
            INSERT OR REPLACE INTO chunk_lineage (
                lineage_id, chunk_id, document_id, source_file_id, collection_id,
                artifact_id, plan_id, step_ordinal, operation, params_json, input_ref,
                output_ref, reversible, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    item.lineage_id,
                    item.chunk_id,
                    item.document_id,
                    item.source_file_id,
                    item.collection_id,
                    item.artifact_id,
                    item.plan_id,
                    item.step_ordinal,
                    item.operation,
                    _json(item.params),
                    item.input_ref,
                    item.output_ref,
                    1 if item.reversible else 0,
                    item.created_at,
                )
                for item in lineages
            ],
        )

    def _upsert_manifest_entries(
        self,
        conn: sqlite3.Connection,
        entries: Sequence[dict[str, Any]],
    ) -> None:
        conn.executemany(
            """
            INSERT OR REPLACE INTO manifest_entries (
                manifest_id, collection_id, source_file_id, document_id, status,
                reason, metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    item["manifest_id"],
                    item["collection_id"],
                    item["source_file_id"],
                    item.get("document_id"),
                    item["status"],
                    item.get("reason"),
                    _json(item.get("metadata")),
                    item["created_at"],
                )
                for item in entries
            ],
        )

    def _upsert_ingest_job(self, conn: sqlite3.Connection, job: dict[str, Any]) -> None:
        conn.execute(
            """
            INSERT OR REPLACE INTO ingest_jobs (
                job_id, collection_id, source_uri, status, started_at, finished_at,
                files_seen, files_ready, files_failed, documents_indexed, chunks_indexed,
                config_json, error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job["job_id"],
                job["collection_id"],
                job["source_uri"],
                job["status"],
                job["started_at"],
                job.get("finished_at"),
                int(job.get("files_seen") or 0),
                int(job.get("files_ready") or 0),
                int(job.get("files_failed") or 0),
                int(job.get("documents_indexed") or 0),
                int(job.get("chunks_indexed") or 0),
                _json(job.get("config")),
                job.get("error"),
            ),
        )

    def _upsert_index_builds(
        self,
        conn: sqlite3.Connection,
        builds: Sequence[IndexBuildRecord],
    ) -> None:
        now = int(time.time() * 1000)
        conn.executemany(
            """
            INSERT OR REPLACE INTO index_builds (
                build_id, collection_id, profile_id, index_type, status,
                documents_indexed, chunks_indexed, metadata_json, created_at, completed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    item.build_id,
                    item.collection_id,
                    item.profile_id,
                    item.index_type,
                    item.status,
                    item.documents_indexed,
                    item.chunks_indexed,
                    _json(item.metadata),
                    item.created_at,
                    item.completed_at,
                )
                for item in builds
            ],
        )
        conn.executemany(
            """
            INSERT OR REPLACE INTO index_catalog (
                profile_id, collection_id, index_type, status, build_id, config_json,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    item.profile_id,
                    item.collection_id,
                    item.index_type,
                    item.status,
                    item.build_id,
                    _json(item.metadata),
                    item.created_at,
                    now,
                )
                for item in builds
            ],
        )

    def _rebuild_fts(
        self,
        conn: sqlite3.Connection,
        collection_id: str,
        chunks: Sequence[KnowledgeChunk],
    ) -> None:
        conn.execute("DELETE FROM fts_chunks WHERE collection_id = ?", (collection_id,))
        conn.executemany(
            """
            INSERT INTO fts_chunks (
                chunk_id, collection_id, document_id, source_path, search_text
            ) VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    chunk.chunk_id,
                    chunk.collection_id,
                    chunk.doc_id,
                    chunk.source_path,
                    _search_text(
                        chunk.text,
                        chunk.title,
                        chunk.source,
                        chunk.source_path,
                        chunk.section,
                    ),
                )
                for chunk in chunks
            ],
        )


def _legacy_source_file(doc: KnowledgeDocument, snapshot_id: str, now: int) -> SourceFileRecord:
    source_file_id = doc.source_file_id or make_stable_id(
        "sf", doc.collection_id, doc.source_path, doc.doc_id
    )
    return SourceFileRecord(
        source_file_id=source_file_id,
        collection_id=doc.collection_id,
        snapshot_id=snapshot_id,
        source_path=doc.source_path,
        absolute_path=doc.source_path,
        file_name=Path(doc.source_path).name,
        extension=doc.file_type,
        size_bytes=0,
        content_sha256=doc.content_sha256 or doc.doc_id,
        status="ready",
        discovered_at=now,
        metadata={"legacy": True},
    )


def _normalize_doc(doc: KnowledgeDocument) -> KnowledgeDocument:
    if doc.source_file_id:
        return doc
    return KnowledgeDocument(
        **{
            **doc.to_json(),
            "source_file_id": make_stable_id(
                "sf", doc.collection_id, doc.source_path, doc.doc_id
            ),
        }
    )


def _normalize_chunk(
    chunk: KnowledgeChunk,
    source_file_id: str | None = None,
) -> KnowledgeChunk:
    if chunk.source_file_id:
        return chunk
    return KnowledgeChunk(
        **{
            **chunk.to_json(),
            "source_file_id": source_file_id
            or make_stable_id("sf", chunk.collection_id, chunk.source_path, chunk.doc_id),
        }
    )


def _job_to_wire(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "jobId": row["job_id"],
        "collectionId": row["collection_id"],
        "sourceUri": row["source_uri"],
        "status": row["status"],
        "startedAt": row["started_at"],
        "finishedAt": row["finished_at"],
        "filesSeen": row["files_seen"],
        "filesReady": row["files_ready"],
        "filesFailed": row["files_failed"],
        "documentsIndexed": row["documents_indexed"],
        "chunksIndexed": row["chunks_indexed"],
        "config": _loads(row["config_json"], {}),
        "error": row["error"],
    }
