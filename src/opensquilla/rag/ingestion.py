"""RAG source ingestion and indexing."""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from typing import Any

from opensquilla.gateway.config import RagConfig
from opensquilla.memory.embedding import EmbeddingProvider

from .chunking import chunk_document
from .parsers import ParserRegistry, looks_binary
from .scanner import ScanCandidate, ScanSkip, scan_source
from .store import RagStore
from .types import (
    RagChunk,
    RagDocument,
    RagDocumentStatus,
    RagEmbedding,
    RagIndexJob,
    RagJobStatus,
    RagSourceStatus,
)


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _document_id(source_id: str, relative_path: str) -> str:
    raw = f"{source_id}\0{relative_path}".encode("utf-8", errors="replace")
    return "doc_" + hashlib.sha256(raw).hexdigest()[:24]


def _chunk_id(document_id: str, chunk_index: int, content_hash: str) -> str:
    raw = f"{document_id}\0{chunk_index}\0{content_hash}".encode("utf-8", errors="replace")
    return "chk_" + hashlib.sha256(raw).hexdigest()[:24]


class IngestionService:
    def __init__(
        self,
        *,
        store: RagStore,
        config: RagConfig,
        embedding_provider: EmbeddingProvider | None = None,
        embedding_fingerprint: str | None = None,
        embedding_base_url: str | None = None,
    ) -> None:
        self.store = store
        self.config = config
        self.embedding_provider = embedding_provider
        self.embedding_fingerprint = embedding_fingerprint
        self.embedding_base_url = embedding_base_url
        self.parsers = ParserRegistry()
        self._locks: dict[str, Any] = {}

    async def sync_source(self, source_id: str, *, force: bool = False) -> RagIndexJob:
        source = await self.store.get_source(source_id)
        if source is None:
            raise KeyError(f"RAG source not found: {source_id}")
        scan_id = "scan_" + uuid.uuid4().hex[:16]
        job = await self.store.create_job(
            job_id="job_" + uuid.uuid4().hex[:16],
            job_type="sync",
            collection_id=source.collection_id,
            source_id=source.source_id,
            scan_id=scan_id,
            metadata={"force": force},
        )
        started = job.started_at
        await self.store.update_source_status(
            source.source_id,
            status=RagSourceStatus.STALE,
            stale_reason="sync_running",
            scan_started_at=started,
        )
        scan_results = scan_source(source, config=self.config)
        source_missing = (
            scan_results
            and isinstance(scan_results[0], ScanSkip)
            and scan_results[0].reason == "source_missing"
        )
        if source_missing:
            await self.store.update_job_progress(
                job.job_id,
                files_failed=1,
                metadata={"reason": "source_missing"},
            )
            finished = await self.store.finish_job(
                job.job_id,
                status=RagJobStatus.FAILED,
                error_code="source_missing",
                error_message="RAG source root does not exist",
            )
            await self.store.update_source_status(
                source.source_id,
                status=RagSourceStatus.MISSING,
                stale_reason="source_missing",
                last_error="RAG source root does not exist",
                scan_finished_at=finished.finished_at,
            )
            return finished

        counters = {
            "files_seen": 0,
            "files_indexed": 0,
            "files_skipped": 0,
            "files_failed": 0,
            "chunks_written": 0,
            "embeddings_written": 0,
        }
        fatal_limit = False
        for item in scan_results:
            if isinstance(item, ScanSkip):
                counters["files_skipped"] += 1
                if item.reason in {"source_file_limit", "source_size_limit"}:
                    fatal_limit = True
                continue
            counters["files_seen"] += 1
            try:
                indexed, chunk_count, embedding_count = await self._index_candidate(
                    item,
                    source_id=source.source_id,
                    collection_id=source.collection_id,
                    scan_id=scan_id,
                    force=force,
                )
                if indexed:
                    counters["files_indexed"] += 1
                    counters["chunks_written"] += chunk_count
                    counters["embeddings_written"] += embedding_count
                else:
                    counters["files_skipped"] += 1
            except Exception as exc:  # noqa: BLE001
                counters["files_failed"] += 1
                await self.store.record_error(
                    error_id="err_" + uuid.uuid4().hex[:16],
                    job_id=job.job_id,
                    collection_id=source.collection_id,
                    source_id=source.source_id,
                    document_id=_document_id(source.source_id, item.relative_path),
                    relative_path=item.relative_path,
                    phase="ingestion",
                    code="parser_failed",
                    message=str(exc),
                )
        removed = 0
        if not fatal_limit:
            removed = await self.store.mark_removed_documents_not_seen(source.source_id, scan_id)
        metadata = {"removed": removed, "force": force}
        await self.store.update_job_progress(job.job_id, **counters, metadata=metadata)
        status = RagJobStatus.SUCCEEDED
        if counters["files_failed"] or fatal_limit:
            status = RagJobStatus.PARTIAL
        finished = await self.store.finish_job(job.job_id, status=status, metadata=metadata)
        source_status = (
            RagSourceStatus.ACTIVE
            if status is RagJobStatus.SUCCEEDED
            else RagSourceStatus.STALE
        )
        await self.store.update_source_status(
            source.source_id,
            status=source_status,
            stale_reason=None if status is RagJobStatus.SUCCEEDED else "partial_sync",
            last_error=None if status is RagJobStatus.SUCCEEDED else "Some files failed to index",
            scan_finished_at=finished.finished_at,
            successful_scan_at=finished.finished_at if status is RagJobStatus.SUCCEEDED else None,
            indexed_at=finished.finished_at,
        )
        return finished

    async def _index_candidate(
        self,
        candidate: ScanCandidate,
        *,
        source_id: str,
        collection_id: str,
        scan_id: str,
        force: bool,
    ) -> tuple[bool, int, int]:
        document_id = _document_id(source_id, candidate.relative_path)
        existing = await self.store.get_document_by_path(source_id, candidate.relative_path)
        if (
            existing
            and not force
            and existing.size_bytes == candidate.size_bytes
            and existing.mtime_ns == candidate.mtime_ns
            and existing.status == RagDocumentStatus.ACTIVE
        ):
            await self.store.mark_document_seen(
                existing.document_id,
                scan_id=scan_id,
                size_bytes=candidate.size_bytes,
                mtime_ns=candidate.mtime_ns,
                absolute_path_snapshot=str(candidate.path),
            )
            return False, 0, 0
        if looks_binary(candidate.path):
            raise ValueError("binary file skipped")
        content_hash = _file_hash(candidate.path)
        if existing and not force and existing.content_hash == content_hash:
            await self.store.mark_document_seen(
                existing.document_id,
                scan_id=scan_id,
                size_bytes=candidate.size_bytes,
                mtime_ns=candidate.mtime_ns,
                absolute_path_snapshot=str(candidate.path),
            )
            return False, 0, 0
        parser = self.parsers.parser_for(candidate.extension)
        if parser is None:
            raise ValueError(f"unsupported extension: {candidate.extension}")
        parsed = await parser.parse(candidate.path, relative_path=candidate.relative_path)
        drafts = chunk_document(
            parsed,
            chunk_size=self.config.chunk_size,
            chunk_overlap=self.config.chunk_overlap,
        )
        chunks = [
            RagChunk(
                chunk_id=_chunk_id(document_id, draft.chunk_index, draft.content_hash),
                document_id=document_id,
                collection_id=collection_id,
                source_id=source_id,
                relative_path=candidate.relative_path,
                chunk_index=draft.chunk_index,
                content=draft.content,
                content_hash=draft.content_hash,
                title=parsed.title,
                section=draft.section,
                line_start=draft.line_start,
                line_end=draft.line_end,
            )
            for draft in drafts
        ]
        document = RagDocument(
            document_id=document_id,
            collection_id=collection_id,
            source_id=source_id,
            relative_path=candidate.relative_path,
            absolute_path_snapshot=str(candidate.path),
            title=parsed.title,
            extension=candidate.extension,
            size_bytes=candidate.size_bytes,
            mtime_ns=candidate.mtime_ns,
            content_hash=content_hash,
            parser=parsed.parser,
            status=RagDocumentStatus.ACTIVE,
            last_seen_scan_id=scan_id,
        )
        embeddings: list[RagEmbedding] = []
        vector_rows: list[tuple[str, list[float]]] = []
        if self.embedding_provider is not None and chunks:
            vectors = await self.embedding_provider.embed_batch([chunk.content for chunk in chunks])
            if vectors:
                await self.store.initialize(vector_dimensions=len(vectors[0]))
            for chunk, vector in zip(chunks, vectors, strict=False):
                embeddings.append(
                    RagEmbedding(
                        chunk_id=chunk.chunk_id,
                        provider=self.embedding_provider.provider_id,
                        model=self.embedding_provider.model,
                        base_url=self.embedding_base_url,
                        dimensions=len(vector),
                        fingerprint=self.embedding_fingerprint or "unknown",
                        embedding=list(vector),
                    )
                )
                vector_rows.append((chunk.chunk_id, list(vector)))
        await self.store.replace_document(
            document,
            chunks,
            embeddings=embeddings,
            vector_rows=vector_rows,
        )
        return True, len(chunks), len(embeddings)
