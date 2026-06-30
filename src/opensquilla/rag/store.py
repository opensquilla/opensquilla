"""SQLite store for local document RAG."""

from __future__ import annotations

import importlib
import json
import math
import struct
import time
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

import structlog

from opensquilla.compat import aiosqlite

from .errors import RagStorageError
from .schema import DDL, RAG_SCHEMA_VERSION, vector_table_ddl
from .types import (
    RagChunk,
    RagCollection,
    RagDocument,
    RagDocumentStatus,
    RagEmbedding,
    RagIndexJob,
    RagJobStatus,
    RagRawHit,
    RagSource,
    RagSourceMode,
    RagSourceStatus,
)

log = structlog.get_logger(__name__)


def _now() -> float:
    return time.time()


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def _float_list_to_blob(floats: Sequence[float]) -> bytes:
    return struct.pack(f"{len(floats)}f", *[float(v) for v in floats])


def _l2_normalize_vector(vector: Sequence[float]) -> list[float]:
    norm = math.sqrt(sum(float(value) * float(value) for value in vector))
    if norm <= 0.0 or not math.isfinite(norm):
        return [float(value) for value in vector]
    return [float(value) / norm for value in vector]


def _vector_distance_to_score(distance: float) -> float:
    return max(0.0, 1.0 - distance / 2.0)


class RagStore:
    """Persistent RAG store backed by SQLite, FTS5 and optional sqlite-vec."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self._db: aiosqlite.Connection | None = None
        self._vec_available = False
        self._vec_dimensions: int | None = None

    @property
    def vec_available(self) -> bool:
        return self._vec_available

    @property
    def vec_dimensions(self) -> int | None:
        return self._vec_dimensions

    async def initialize(self, *, vector_dimensions: int | None = None) -> None:
        if self._db is not None:
            if vector_dimensions and not self._vec_available:
                await self._probe_vec_extension(vector_dimensions)
            return
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(self.db_path))
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA busy_timeout = 5000")
        await self._db.execute("PRAGMA journal_mode = WAL")
        await self._db.execute("PRAGMA foreign_keys = ON")
        await self._db.executescript(DDL)
        await self._db.commit()
        dimensions = vector_dimensions or await self._existing_vector_dimensions()
        if dimensions:
            await self._probe_vec_extension(dimensions)

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    def _require_db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RagStorageError("RAG store is not initialized")
        return self._db

    async def _probe_vec_extension(self, dimensions: int) -> None:
        db = self._require_db()
        try:
            sqlite_vec = importlib.import_module("sqlite_vec")
            await db.enable_load_extension(True)
            await db.load_extension(sqlite_vec.loadable_path())
            await db.enable_load_extension(False)
            await db.executescript(vector_table_ddl(dimensions))
            await db.commit()
            self._vec_available = True
            self._vec_dimensions = dimensions
        except Exception as exc:  # noqa: BLE001
            try:
                await db.enable_load_extension(False)
            except Exception:
                pass
            self._vec_available = False
            self._vec_dimensions = None
            log.warning("rag.sqlite_vec_unavailable", error=str(exc))

    async def _existing_vector_dimensions(self) -> int | None:
        db = self._require_db()
        async with db.execute(
            """
            SELECT dimensions
            FROM rag_embeddings
            WHERE status = 'active' AND dimensions > 0
            GROUP BY dimensions
            ORDER BY COUNT(*) DESC, MAX(updated_at) DESC
            LIMIT 1
            """
        ) as cur:
            row = await cur.fetchone()
        return int(row["dimensions"]) if row else None

    async def schema_version(self) -> int:
        db = self._require_db()
        async with db.execute("SELECT value FROM rag_meta WHERE key='schema_version'") as cur:
            row = await cur.fetchone()
        return int(row["value"]) if row else RAG_SCHEMA_VERSION

    async def ensure_default_collection(self) -> RagCollection:
        existing = await self.get_collection("default")
        if existing:
            return existing
        now = _now()
        collection = RagCollection(
            collection_id="default",
            name="Default",
            enabled=True,
            created_at=now,
            updated_at=now,
        )
        await self.upsert_collection(collection)
        return collection

    async def upsert_collection(self, collection: RagCollection) -> RagCollection:
        db = self._require_db()
        now = _now()
        created_at = collection.created_at or now
        updated_at = now
        await db.execute(
            """
            INSERT INTO rag_collections(
              collection_id, name, enabled, metadata_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(collection_id) DO UPDATE SET
              name=excluded.name,
              enabled=excluded.enabled,
              metadata_json=excluded.metadata_json,
              updated_at=excluded.updated_at
            """,
            (
                collection.collection_id,
                collection.name,
                1 if collection.enabled else 0,
                _json_dumps(collection.metadata),
                created_at,
                updated_at,
            ),
        )
        await db.commit()
        return (await self.get_collection(collection.collection_id)) or collection

    async def get_collection(self, collection_id: str) -> RagCollection | None:
        db = self._require_db()
        async with db.execute(
            "SELECT * FROM rag_collections WHERE collection_id = ?",
            (collection_id,),
        ) as cur:
            row = await cur.fetchone()
        return self._row_to_collection(row) if row else None

    async def list_collections(self) -> list[RagCollection]:
        db = self._require_db()
        async with db.execute("SELECT * FROM rag_collections ORDER BY collection_id") as cur:
            rows = await cur.fetchall()
        return [self._row_to_collection(row) for row in rows]

    async def upsert_source(self, source: RagSource) -> RagSource:
        db = self._require_db()
        now = _now()
        created_at = source.created_at or now
        updated_at = now
        await db.execute(
            """
            INSERT INTO rag_sources(
              source_id, collection_id, mode, root_path, display_name,
              include_json, exclude_json, enabled, sync_policy, scale_hint,
              status, stale_reason, last_error, last_scan_started_at,
              last_scan_finished_at, last_successful_scan_at, last_indexed_at,
              created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'manual', 'default', ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_id) DO UPDATE SET
              collection_id=excluded.collection_id,
              mode=excluded.mode,
              root_path=excluded.root_path,
              display_name=excluded.display_name,
              include_json=excluded.include_json,
              exclude_json=excluded.exclude_json,
              enabled=excluded.enabled,
              status=excluded.status,
              stale_reason=excluded.stale_reason,
              last_error=excluded.last_error,
              last_scan_started_at=excluded.last_scan_started_at,
              last_scan_finished_at=excluded.last_scan_finished_at,
              last_successful_scan_at=excluded.last_successful_scan_at,
              last_indexed_at=excluded.last_indexed_at,
              updated_at=excluded.updated_at
            """,
            (
                source.source_id,
                source.collection_id,
                source.mode.value,
                source.root_path,
                source.display_name,
                _json_dumps(list(source.include)),
                _json_dumps(list(source.exclude)),
                1 if source.enabled else 0,
                source.status.value,
                source.stale_reason,
                source.last_error,
                source.last_scan_started_at,
                source.last_scan_finished_at,
                source.last_successful_scan_at,
                source.last_indexed_at,
                created_at,
                updated_at,
            ),
        )
        await db.commit()
        return (await self.get_source(source.source_id)) or source

    async def get_source(self, source_id: str) -> RagSource | None:
        db = self._require_db()
        async with db.execute("SELECT * FROM rag_sources WHERE source_id = ?", (source_id,)) as cur:
            row = await cur.fetchone()
        return self._row_to_source(row) if row else None

    async def find_source_by_root(self, collection_id: str, root_path: str) -> RagSource | None:
        db = self._require_db()
        async with db.execute(
            """
            SELECT * FROM rag_sources
            WHERE collection_id = ? AND root_path = ?
            LIMIT 1
            """,
            (collection_id, root_path),
        ) as cur:
            row = await cur.fetchone()
        return self._row_to_source(row) if row else None

    async def list_sources(
        self,
        *,
        collection_id: str | None = None,
        include_disabled: bool = True,
    ) -> list[RagSource]:
        db = self._require_db()
        clauses: list[str] = []
        params: list[Any] = []
        if collection_id:
            clauses.append("collection_id = ?")
            params.append(collection_id)
        if not include_disabled:
            clauses.append("enabled = 1")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        async with db.execute(
            f"SELECT * FROM rag_sources {where} ORDER BY collection_id, display_name",
            params,
        ) as cur:
            rows = await cur.fetchall()
        return [self._row_to_source(row) for row in rows]

    async def update_source_status(
        self,
        source_id: str,
        *,
        status: RagSourceStatus,
        stale_reason: str | None = None,
        last_error: str | None = None,
        scan_started_at: float | None = None,
        scan_finished_at: float | None = None,
        successful_scan_at: float | None = None,
        indexed_at: float | None = None,
    ) -> None:
        db = self._require_db()
        await db.execute(
            """
            UPDATE rag_sources
            SET status = ?, stale_reason = ?, last_error = ?,
                last_scan_started_at = COALESCE(?, last_scan_started_at),
                last_scan_finished_at = COALESCE(?, last_scan_finished_at),
                last_successful_scan_at = COALESCE(?, last_successful_scan_at),
                last_indexed_at = COALESCE(?, last_indexed_at),
                updated_at = ?
            WHERE source_id = ?
            """,
            (
                status.value,
                stale_reason,
                last_error,
                scan_started_at,
                scan_finished_at,
                successful_scan_at,
                indexed_at,
                _now(),
                source_id,
            ),
        )
        await db.commit()

    async def create_job(
        self,
        *,
        job_id: str,
        job_type: str,
        collection_id: str | None,
        source_id: str | None,
        scan_id: str,
        status: RagJobStatus = RagJobStatus.RUNNING,
        metadata: dict[str, Any] | None = None,
    ) -> RagIndexJob:
        db = self._require_db()
        started_at = _now()
        await db.execute(
            """
            INSERT INTO rag_index_jobs(
              job_id, job_type, collection_id, source_id, status, scan_id, started_at, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                job_type,
                collection_id,
                source_id,
                status.value,
                scan_id,
                started_at,
                _json_dumps(metadata or {}),
            ),
        )
        await db.commit()
        return (await self.get_job(job_id)) or RagIndexJob(
            job_id=job_id,
            job_type=job_type,
            collection_id=collection_id,
            source_id=source_id,
            status=status,
            scan_id=scan_id,
            started_at=started_at,
        )

    async def get_job(self, job_id: str) -> RagIndexJob | None:
        db = self._require_db()
        async with db.execute("SELECT * FROM rag_index_jobs WHERE job_id = ?", (job_id,)) as cur:
            row = await cur.fetchone()
        return self._row_to_job(row) if row else None

    async def update_job_progress(self, job_id: str, **fields: Any) -> None:
        allowed = {
            "files_seen",
            "files_indexed",
            "files_skipped",
            "files_failed",
            "chunks_written",
            "embeddings_written",
        }
        updates: list[str] = []
        params: list[Any] = []
        for key, value in fields.items():
            if key in allowed and value is not None:
                updates.append(f"{key} = ?")
                params.append(int(value))
        metadata = fields.get("metadata")
        if metadata is not None:
            updates.append("metadata_json = ?")
            params.append(_json_dumps(metadata))
        if not updates:
            return
        params.append(job_id)
        db = self._require_db()
        await db.execute(
            f"UPDATE rag_index_jobs SET {', '.join(updates)} WHERE job_id = ?",
            params,
        )
        await db.commit()

    async def finish_job(
        self,
        job_id: str,
        *,
        status: RagJobStatus,
        error_code: str | None = None,
        error_message: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RagIndexJob:
        db = self._require_db()
        if metadata is None:
            await db.execute(
                """
                UPDATE rag_index_jobs
                SET status = ?, finished_at = ?, error_code = ?, error_message = ?
                WHERE job_id = ?
                """,
                (status.value, _now(), error_code, error_message, job_id),
            )
        else:
            await db.execute(
                """
                UPDATE rag_index_jobs
                SET status = ?, finished_at = ?, error_code = ?, error_message = ?,
                    metadata_json = ?
                WHERE job_id = ?
                """,
                (status.value, _now(), error_code, error_message, _json_dumps(metadata), job_id),
            )
        await db.commit()
        job = await self.get_job(job_id)
        if job is None:
            raise RagStorageError("RAG job disappeared after finish", details={"job_id": job_id})
        return job

    async def get_document_by_path(self, source_id: str, relative_path: str) -> RagDocument | None:
        db = self._require_db()
        async with db.execute(
            """
            SELECT * FROM rag_documents
            WHERE source_id = ? AND relative_path = ?
            """,
            (source_id, relative_path),
        ) as cur:
            row = await cur.fetchone()
        return self._row_to_document(row) if row else None

    async def replace_document(
        self,
        document: RagDocument,
        chunks: Sequence[RagChunk],
        *,
        embeddings: Sequence[RagEmbedding] = (),
        vector_rows: Sequence[tuple[str, Sequence[float]]] = (),
    ) -> None:
        db = self._require_db()
        now = _now()
        await db.execute("BEGIN")
        try:
            await db.execute(
                """
                INSERT INTO rag_documents(
                  document_id, collection_id, source_id, relative_path,
                  absolute_path_snapshot, title, extension, size_bytes, mtime_ns,
                  content_hash, parser, status, last_seen_scan_id, indexed_at,
                  removed_at, last_error, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(document_id) DO UPDATE SET
                  title=excluded.title,
                  absolute_path_snapshot=excluded.absolute_path_snapshot,
                  extension=excluded.extension,
                  size_bytes=excluded.size_bytes,
                  mtime_ns=excluded.mtime_ns,
                  content_hash=excluded.content_hash,
                  parser=excluded.parser,
                  status=excluded.status,
                  last_seen_scan_id=excluded.last_seen_scan_id,
                  indexed_at=excluded.indexed_at,
                  removed_at=excluded.removed_at,
                  last_error=excluded.last_error,
                  updated_at=excluded.updated_at
                """,
                (
                    document.document_id,
                    document.collection_id,
                    document.source_id,
                    document.relative_path,
                    document.absolute_path_snapshot,
                    document.title,
                    document.extension,
                    document.size_bytes,
                    document.mtime_ns,
                    document.content_hash,
                    document.parser,
                    document.status.value,
                    document.last_seen_scan_id,
                    document.indexed_at or now,
                    document.removed_at,
                    document.last_error,
                    document.created_at or now,
                    now,
                ),
            )
            await self._delete_document_index(document.document_id, in_transaction=True)
            for chunk in chunks:
                await db.execute(
                    """
                    INSERT INTO rag_chunks(
                      chunk_id, document_id, collection_id, source_id, relative_path,
                      chunk_index, content, content_hash, title, section, line_start,
                      line_end, page, token_count, status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        chunk.chunk_id,
                        chunk.document_id,
                        chunk.collection_id,
                        chunk.source_id,
                        chunk.relative_path,
                        chunk.chunk_index,
                        chunk.content,
                        chunk.content_hash,
                        chunk.title,
                        chunk.section,
                        chunk.line_start,
                        chunk.line_end,
                        chunk.page,
                        chunk.token_count,
                        chunk.status,
                        chunk.created_at or now,
                        now,
                    ),
                )
                await db.execute(
                    """
                    INSERT INTO rag_chunks_fts(
                      content, title, relative_path, chunk_id, document_id, collection_id, source_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        chunk.content,
                        chunk.title or "",
                        chunk.relative_path,
                        chunk.chunk_id,
                        chunk.document_id,
                        chunk.collection_id,
                        chunk.source_id,
                    ),
                )
            for embedding in embeddings:
                await db.execute(
                    """
                    INSERT OR REPLACE INTO rag_embeddings(
                      chunk_id, provider, model, base_url, dimensions, fingerprint,
                      embedding_json, status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        embedding.chunk_id,
                        embedding.provider,
                        embedding.model,
                        embedding.base_url,
                        embedding.dimensions,
                        embedding.fingerprint,
                        _json_dumps(embedding.embedding),
                        embedding.status,
                        now,
                        now,
                    ),
                )
            if self._vec_available and vector_rows:
                for chunk_id, vector in vector_rows:
                    await db.execute(
                        "INSERT OR REPLACE INTO rag_chunks_vec(chunk_id, embedding) VALUES (?, ?)",
                        (chunk_id, _float_list_to_blob(_l2_normalize_vector(vector))),
                    )
            await db.commit()
        except Exception:
            await db.rollback()
            raise

    async def mark_document_seen(
        self,
        document_id: str,
        *,
        scan_id: str,
        size_bytes: int,
        mtime_ns: int,
        absolute_path_snapshot: str,
    ) -> None:
        db = self._require_db()
        await db.execute(
            """
            UPDATE rag_documents
            SET last_seen_scan_id = ?, size_bytes = ?, mtime_ns = ?,
                absolute_path_snapshot = ?, updated_at = ?
            WHERE document_id = ?
            """,
            (scan_id, size_bytes, mtime_ns, absolute_path_snapshot, _now(), document_id),
        )
        await db.commit()

    async def mark_removed_documents_not_seen(self, source_id: str, scan_id: str) -> int:
        db = self._require_db()
        async with db.execute(
            """
            SELECT document_id FROM rag_documents
            WHERE source_id = ? AND status = 'active'
              AND (last_seen_scan_id IS NULL OR last_seen_scan_id != ?)
            """,
            (source_id, scan_id),
        ) as cur:
            rows = await cur.fetchall()
        document_ids = [row["document_id"] for row in rows]
        for document_id in document_ids:
            await self._delete_document_index(document_id)
            await db.execute(
                """
                UPDATE rag_documents
                SET status = 'removed', removed_at = ?, updated_at = ?
                WHERE document_id = ?
                """,
                (_now(), _now(), document_id),
            )
        await db.commit()
        return len(document_ids)

    async def _delete_document_index(
        self,
        document_id: str,
        *,
        in_transaction: bool = False,
    ) -> None:
        db = self._require_db()
        async with db.execute(
            "SELECT chunk_id FROM rag_chunks WHERE document_id = ?",
            (document_id,),
        ) as cur:
            rows = await cur.fetchall()
        chunk_ids = [row["chunk_id"] for row in rows]
        await db.execute("DELETE FROM rag_chunks_fts WHERE document_id = ?", (document_id,))
        for chunk_id in chunk_ids:
            await db.execute("DELETE FROM rag_embeddings WHERE chunk_id = ?", (chunk_id,))
            if self._vec_available:
                try:
                    await db.execute("DELETE FROM rag_chunks_vec WHERE chunk_id = ?", (chunk_id,))
                except Exception:
                    pass
        await db.execute("DELETE FROM rag_chunks WHERE document_id = ?", (document_id,))
        if not in_transaction:
            await db.commit()

    async def delete_source(self, source_id: str) -> bool:
        source = await self.get_source(source_id)
        if source is None:
            return False
        db = self._require_db()
        await db.execute("BEGIN")
        try:
            async with db.execute(
                "SELECT document_id FROM rag_documents WHERE source_id = ?",
                (source_id,),
            ) as cur:
                rows = await cur.fetchall()
            for row in rows:
                await self._delete_document_index(row["document_id"], in_transaction=True)
            await db.execute("DELETE FROM rag_documents WHERE source_id = ?", (source_id,))
            await db.execute("DELETE FROM rag_errors WHERE source_id = ?", (source_id,))
            await db.execute("DELETE FROM rag_index_jobs WHERE source_id = ?", (source_id,))
            await db.execute("DELETE FROM rag_sources WHERE source_id = ?", (source_id,))
            await db.commit()
            return True
        except Exception:
            await db.rollback()
            raise

    async def record_error(
        self,
        *,
        error_id: str,
        job_id: str | None,
        collection_id: str | None,
        source_id: str | None,
        document_id: str | None,
        relative_path: str | None,
        phase: str,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        db = self._require_db()
        await db.execute(
            """
            INSERT INTO rag_errors(
              error_id, job_id, collection_id, source_id, document_id,
              relative_path, phase, code, message, details_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                error_id,
                job_id,
                collection_id,
                source_id,
                document_id,
                relative_path,
                phase,
                code,
                message,
                _json_dumps(details or {}),
                _now(),
            ),
        )
        await db.commit()

    async def search_fts(
        self,
        query: str,
        *,
        collection_id: str | None = None,
        source_id: str | None = None,
        path_prefix: str | None = None,
        limit: int = 8,
    ) -> list[RagRawHit]:
        db = self._require_db()
        filters, params = self._search_filters(collection_id, source_id, path_prefix, alias="c")
        where = f"AND {' AND '.join(filters)}" if filters else ""
        sql = f"""
        SELECT
          c.chunk_id, c.document_id, c.collection_id, c.source_id, c.relative_path,
          c.chunk_index, c.content, c.title, c.line_start, c.line_end,
          s.status AS source_status,
          bm25(rag_chunks_fts) AS rank
        FROM rag_chunks_fts
        JOIN rag_chunks c ON c.chunk_id = rag_chunks_fts.chunk_id
        JOIN rag_sources s ON s.source_id = c.source_id
        WHERE rag_chunks_fts MATCH ?
          AND c.status = 'active'
          AND s.enabled = 1
          {where}
        ORDER BY rank ASC, c.relative_path ASC, c.chunk_index ASC
        LIMIT ?
        """
        async with db.execute(sql, [query, *params, limit]) as cur:
            rows = await cur.fetchall()
        hits: list[RagRawHit] = []
        ranks = [float(row["rank"]) for row in rows] or [0.0]
        worst = max(ranks)
        best = min(ranks)
        span = max(1e-9, worst - best)
        for row in rows:
            rank = float(row["rank"])
            score = 1.0 if worst == best else max(0.0, min(1.0, 1.0 - (rank - best) / span))
            hits.append(self._row_to_hit(row, text_score=score))
        return hits

    async def search_vector(
        self,
        embedding: Sequence[float],
        *,
        collection_id: str | None = None,
        source_id: str | None = None,
        path_prefix: str | None = None,
        limit: int = 8,
    ) -> list[RagRawHit]:
        if not self._vec_available:
            return []
        db = self._require_db()
        filters, params = self._search_filters(collection_id, source_id, path_prefix, alias="c")
        where = f"AND {' AND '.join(filters)}" if filters else ""
        sql = """
        SELECT chunk_id, distance
        FROM rag_chunks_vec
        WHERE embedding MATCH ?
        ORDER BY distance
        LIMIT ?
        """
        try:
            async with db.execute(
                sql,
                (_float_list_to_blob(_l2_normalize_vector(embedding)), limit * 4),
            ) as cur:
                vec_rows = await cur.fetchall()
        except Exception as exc:  # noqa: BLE001
            log.warning("rag.vector_search_failed", error=str(exc))
            return []
        if not vec_rows:
            return []
        chunk_ids = [row["chunk_id"] for row in vec_rows]
        distance_by_id = {row["chunk_id"]: float(row["distance"]) for row in vec_rows}
        placeholders = ",".join("?" for _ in chunk_ids)
        join_sql = f"""
        SELECT
          c.chunk_id, c.document_id, c.collection_id, c.source_id, c.relative_path,
          c.chunk_index, c.content, c.title, c.line_start, c.line_end,
          s.status AS source_status
        FROM rag_chunks c
        JOIN rag_sources s ON s.source_id = c.source_id
        WHERE c.chunk_id IN ({placeholders})
          AND c.status = 'active'
          AND s.enabled = 1
          {where}
        """
        async with db.execute(join_sql, [*chunk_ids, *params]) as cur:
            rows = await cur.fetchall()
        by_id = {row["chunk_id"]: row for row in rows}
        hits: list[RagRawHit] = []
        for chunk_id in chunk_ids:
            row = by_id.get(chunk_id)
            if row is None:
                continue
            hits.append(
                self._row_to_hit(
                    row,
                    vector_score=_vector_distance_to_score(distance_by_id[chunk_id]),
                )
            )
            if len(hits) >= limit:
                break
        return hits

    def _search_filters(
        self,
        collection_id: str | None,
        source_id: str | None,
        path_prefix: str | None,
        *,
        alias: str,
    ) -> tuple[list[str], list[Any]]:
        filters: list[str] = []
        params: list[Any] = []
        if collection_id:
            filters.append(f"{alias}.collection_id = ?")
            params.append(collection_id)
        if source_id:
            filters.append(f"{alias}.source_id = ?")
            params.append(source_id)
        if path_prefix:
            filters.append(f"{alias}.relative_path LIKE ?")
            params.append(f"{path_prefix}%")
        return filters, params

    async def get_chunk(self, chunk_id: str) -> RagRawHit | None:
        db = self._require_db()
        async with db.execute(
            """
            SELECT
              c.chunk_id, c.document_id, c.collection_id, c.source_id, c.relative_path,
              c.chunk_index, c.content, c.title, c.line_start, c.line_end,
              s.status AS source_status
            FROM rag_chunks c
            JOIN rag_sources s ON s.source_id = c.source_id
            WHERE c.chunk_id = ? AND c.status = 'active'
            """,
            (chunk_id,),
        ) as cur:
            row = await cur.fetchone()
        return self._row_to_hit(row) if row else None

    async def get_document_chunks(
        self,
        *,
        document_id: str | None = None,
        source_id: str | None = None,
        relative_path: str | None = None,
    ) -> list[RagRawHit]:
        db = self._require_db()
        clauses = ["c.status = 'active'"]
        params: list[Any] = []
        if document_id:
            clauses.append("c.document_id = ?")
            params.append(document_id)
        if source_id and relative_path:
            clauses.append("c.source_id = ?")
            clauses.append("c.relative_path = ?")
            params.extend([source_id, relative_path])
        where = " AND ".join(clauses)
        async with db.execute(
            f"""
            SELECT
              c.chunk_id, c.document_id, c.collection_id, c.source_id, c.relative_path,
              c.chunk_index, c.content, c.title, c.line_start, c.line_end,
              s.status AS source_status
            FROM rag_chunks c
            JOIN rag_sources s ON s.source_id = c.source_id
            WHERE {where}
            ORDER BY c.chunk_index ASC
            """,
            params,
        ) as cur:
            rows = await cur.fetchall()
        return [self._row_to_hit(row) for row in rows]

    async def list_documents(
        self,
        *,
        collection_id: str | None = None,
        source_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[RagDocument], int]:
        db = self._require_db()
        clauses: list[str] = []
        params: list[Any] = []
        if collection_id:
            clauses.append("collection_id = ?")
            params.append(collection_id)
        if source_id:
            clauses.append("source_id = ?")
            params.append(source_id)
        if status:
            clauses.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        async with db.execute(f"SELECT COUNT(*) AS c FROM rag_documents {where}", params) as cur:
            total_row = await cur.fetchone()
        async with db.execute(
            f"""
            SELECT * FROM rag_documents
            {where}
            ORDER BY source_id, relative_path
            LIMIT ? OFFSET ?
            """,
            [*params, limit, offset],
        ) as cur:
            rows = await cur.fetchall()
        return [self._row_to_document(row) for row in rows], int(total_row["c"] if total_row else 0)

    async def recent_jobs(self, *, limit: int = 10) -> list[RagIndexJob]:
        db = self._require_db()
        async with db.execute(
            "SELECT * FROM rag_index_jobs ORDER BY started_at DESC LIMIT ?",
            (limit,),
        ) as cur:
            rows = await cur.fetchall()
        return [self._row_to_job(row) for row in rows]

    async def list_errors(
        self,
        *,
        limit: int = 100,
        source_id: str | None = None,
    ) -> list[dict[str, Any]]:
        db = self._require_db()
        if source_id:
            sql = "SELECT * FROM rag_errors WHERE source_id = ? ORDER BY created_at DESC LIMIT ?"
            params: Iterable[Any] = (source_id, limit)
        else:
            sql = "SELECT * FROM rag_errors ORDER BY created_at DESC LIMIT ?"
            params = (limit,)
        async with db.execute(sql, params) as cur:
            rows = await cur.fetchall()
        return [
            {
                "errorId": row["error_id"],
                "jobId": row["job_id"],
                "collectionId": row["collection_id"],
                "sourceId": row["source_id"],
                "documentId": row["document_id"],
                "path": row["relative_path"],
                "phase": row["phase"],
                "code": row["code"],
                "message": row["message"],
                "details": _json_loads(row["details_json"], {}),
                "createdAt": row["created_at"],
            }
            for row in rows
        ]

    async def status_summary(self) -> dict[str, Any]:
        db = self._require_db()

        async def count(table: str, where: str = "", params: Iterable[Any] = ()) -> int:
            async with db.execute(
                f"SELECT COUNT(*) AS c FROM {table} {where}",
                tuple(params),
            ) as cur:
                row = await cur.fetchone()
            return int(row["c"] if row else 0)

        source_statuses: dict[str, int] = {}
        async with db.execute(
            "SELECT status, COUNT(*) AS c FROM rag_sources GROUP BY status"
        ) as cur:
            for row in await cur.fetchall():
                source_statuses[str(row["status"])] = int(row["c"])
        document_statuses: dict[str, int] = {}
        async with db.execute(
            "SELECT status, COUNT(*) AS c FROM rag_documents GROUP BY status"
        ) as cur:
            for row in await cur.fetchall():
                document_statuses[str(row["status"])] = int(row["c"])
        return {
            "schemaVersion": await self.schema_version(),
            "collections": await count("rag_collections"),
            "sources": await count("rag_sources"),
            "documents": await count("rag_documents"),
            "chunks": await count("rag_chunks", "WHERE status = 'active'"),
            "errors": await count("rag_errors"),
            "sourcesSummary": source_statuses,
            "documentsSummary": document_statuses,
        }

    def _row_to_collection(self, row: Any) -> RagCollection:
        return RagCollection(
            collection_id=row["collection_id"],
            name=row["name"],
            enabled=bool(row["enabled"]),
            metadata=_json_loads(row["metadata_json"], {}),
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
        )

    def _row_to_source(self, row: Any) -> RagSource:
        return RagSource(
            source_id=row["source_id"],
            collection_id=row["collection_id"],
            mode=RagSourceMode(row["mode"]),
            root_path=row["root_path"],
            display_name=row["display_name"],
            include=tuple(_json_loads(row["include_json"], [])),
            exclude=tuple(_json_loads(row["exclude_json"], [])),
            enabled=bool(row["enabled"]),
            status=RagSourceStatus(row["status"]),
            stale_reason=row["stale_reason"],
            last_error=row["last_error"],
            last_scan_started_at=row["last_scan_started_at"],
            last_scan_finished_at=row["last_scan_finished_at"],
            last_successful_scan_at=row["last_successful_scan_at"],
            last_indexed_at=row["last_indexed_at"],
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
        )

    def _row_to_document(self, row: Any) -> RagDocument:
        return RagDocument(
            document_id=row["document_id"],
            collection_id=row["collection_id"],
            source_id=row["source_id"],
            relative_path=row["relative_path"],
            absolute_path_snapshot=row["absolute_path_snapshot"],
            title=row["title"],
            extension=row["extension"],
            size_bytes=int(row["size_bytes"]),
            mtime_ns=int(row["mtime_ns"]),
            content_hash=row["content_hash"],
            parser=row["parser"],
            status=RagDocumentStatus(row["status"]),
            last_seen_scan_id=row["last_seen_scan_id"],
            indexed_at=row["indexed_at"],
            removed_at=row["removed_at"],
            last_error=row["last_error"],
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
        )

    def _row_to_job(self, row: Any) -> RagIndexJob:
        return RagIndexJob(
            job_id=row["job_id"],
            job_type=row["job_type"],
            collection_id=row["collection_id"],
            source_id=row["source_id"],
            status=RagJobStatus(row["status"]),
            scan_id=row["scan_id"] or "",
            started_at=float(row["started_at"]),
            finished_at=row["finished_at"],
            files_seen=int(row["files_seen"]),
            files_indexed=int(row["files_indexed"]),
            files_skipped=int(row["files_skipped"]),
            files_failed=int(row["files_failed"]),
            chunks_written=int(row["chunks_written"]),
            embeddings_written=int(row["embeddings_written"]),
            error_code=row["error_code"],
            error_message=row["error_message"],
            metadata=_json_loads(row["metadata_json"], {}),
        )

    def _row_to_hit(
        self,
        row: Any,
        *,
        text_score: float | None = None,
        vector_score: float | None = None,
    ) -> RagRawHit:
        return RagRawHit(
            chunk_id=row["chunk_id"],
            document_id=row["document_id"],
            collection_id=row["collection_id"],
            source_id=row["source_id"],
            relative_path=row["relative_path"],
            chunk_index=int(row["chunk_index"]),
            content=row["content"],
            title=row["title"],
            line_start=row["line_start"],
            line_end=row["line_end"],
            source_status=row["source_status"],
            text_score=text_score,
            vector_score=vector_score,
        )
