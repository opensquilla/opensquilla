"""Manager facade for local document RAG."""

from __future__ import annotations

import json
import shutil
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from opensquilla.gateway.config import GatewayConfig

from .citations import citation_to_wire, result_to_wire
from .embedding import create_rag_embedding_provider, resolve_rag_embedding
from .errors import RagDisabledError, RagNotFoundError, RagValidationError
from .imports import import_zip_bytes, imported_source_id, replace_directory, safe_archive_name
from .ingestion import IngestionService
from .paths import rag_db_path, rag_state_dir, validate_identifier
from .retrieval import RetrievalService
from .sources import SourceRegistry
from .store import RagStore
from .types import RagCitation, RagSearchRequest, RagSource, RagSourceMode


class RagManager:
    def __init__(
        self,
        *,
        config: GatewayConfig,
        store: RagStore,
        source_registry: SourceRegistry,
        ingestion: IngestionService,
        retrieval: RetrievalService,
        embedding_decision: Any,
    ) -> None:
        self.config = config
        self.store = store
        self.source_registry = source_registry
        self.ingestion = ingestion
        self.retrieval = retrieval
        self.embedding_decision = embedding_decision
        self.enabled = bool(config.rag.enabled)

    async def close(self) -> None:
        await self.store.close()

    async def status(self) -> dict[str, Any]:
        if not self.enabled:
            return {"enabled": False, "reason": "rag_disabled"}
        summary = await self.store.status_summary()
        jobs = [self._job_to_wire(job) for job in await self.store.recent_jobs(limit=10)]
        active_jobs = [
            job for job in jobs if str(job.get("status")) in {"pending", "running"}
        ]
        return {
            "enabled": True,
            "dbPath": str(rag_db_path(self.config)),
            "schemaVersion": summary["schemaVersion"],
            "retrievalMode": self.config.rag.retrieval_mode,
            "embedding": {
                "enabled": self.embedding_decision.enabled,
                "provider": self.embedding_decision.effective_provider,
                "requestedProvider": self.embedding_decision.requested_provider,
                "model": self.embedding_decision.model,
                "dimensions": self.embedding_decision.dimensions,
                "fingerprint": self.embedding_decision.fingerprint,
                "reason": self.embedding_decision.reason,
            },
            "vector": {
                "available": self.store.vec_available,
                "dimensions": self.store.vec_dimensions,
                "indexStatus": "ready" if self.store.vec_available else "unavailable",
            },
            "counts": {
                "collections": summary["collections"],
                "sources": summary["sources"],
                "documents": summary["documents"],
                "chunks": summary["chunks"],
                "errors": summary["errors"],
            },
            "sourcesSummary": summary["sourcesSummary"],
            "documentsSummary": summary["documentsSummary"],
            "recentJobs": jobs,
            "ingestion": {
                "activeJobs": len(active_jobs),
                "isIndexing": bool(active_jobs),
                "latestJob": jobs[0] if jobs else None,
                "lastCompletedJob": next(
                    (job for job in jobs if str(job.get("status")) not in {"pending", "running"}),
                    None,
                ),
                "summary": self._job_status_summary(jobs),
            },
        }

    async def add_source(
        self,
        *,
        path: str,
        collection_id: str = "default",
        source_id: str | None = None,
        name: str | None = None,
        include: Sequence[str] = (),
        exclude: Sequence[str] = (),
        enabled: bool = True,
        index: bool = False,
    ) -> dict[str, Any]:
        self._require_enabled()
        source, created = await self.source_registry.add_source(
            path=path,
            collection_id=collection_id,
            source_id=source_id,
            name=name,
            include=include,
            exclude=exclude,
            enabled=enabled,
        )
        job = await self.ingestion.sync_source(source.source_id) if index else None
        return {
            "source": self._source_to_wire(source),
            "created": created,
            "job": self._job_to_wire(job) if job else None,
        }

    async def import_zip_source(
        self,
        *,
        archive_name: str,
        payload: bytes,
        collection_id: str = "default",
        name: str | None = None,
        index: bool = False,
    ) -> dict[str, Any]:
        self._require_enabled()
        archive_file_name = safe_archive_name(archive_name)
        source_id = imported_source_id(name, archive_file_name, uuid.uuid4().hex[:8])
        import_root = rag_state_dir(self.config) / "imports" / source_id
        tmp_root = import_root.with_name(f".{source_id}.tmp-{uuid.uuid4().hex[:8]}")
        tmp_files = tmp_root / "files"
        final_files = import_root / "files"
        try:
            summary = import_zip_bytes(
                archive_name=archive_file_name,
                payload=payload,
                target_dir=tmp_files,
                config=self.config.rag,
            )
            metadata = {
                "archiveName": archive_file_name,
                "sourceId": source_id,
                "collectionId": collection_id,
                "name": name,
                "import": summary,
            }
            tmp_root.mkdir(parents=True, exist_ok=True)
            (tmp_root / "original.json").write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            replace_directory(tmp_root, import_root)
        except Exception:
            shutil.rmtree(tmp_root, ignore_errors=True)
            raise

        source, created = await self.source_registry.add_source(
            path=str(final_files),
            collection_id=collection_id,
            source_id=source_id,
            name=name or archive_file_name.rsplit(".", 1)[0] or archive_file_name,
            include=(),
            exclude=(),
            enabled=True,
            mode=RagSourceMode.IMPORTED,
        )
        job = await self.ingestion.sync_source(source.source_id) if index else None
        return {
            "source": self._source_to_wire(source),
            "created": created,
            "job": self._job_to_wire(job) if job else None,
            "import": summary,
        }

    async def list_sources(
        self,
        *,
        collection_id: str | None = None,
        include_disabled: bool = True,
    ) -> list[dict[str, Any]]:
        self._require_enabled()
        sources = await self.store.list_sources(
            collection_id=collection_id,
            include_disabled=include_disabled,
        )
        return [self._source_to_wire(source) for source in sources]

    async def list_documents(
        self,
        *,
        collection_id: str | None = None,
        source_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        self._require_enabled()
        docs, total = await self.store.list_documents(
            collection_id=collection_id,
            source_id=source_id,
            status=status,
            limit=limit,
            offset=offset,
        )
        return {
            "kind": "documents",
            "items": [
                {
                    "documentId": doc.document_id,
                    "collectionId": doc.collection_id,
                    "sourceId": doc.source_id,
                    "path": doc.relative_path,
                    "title": doc.title,
                    "status": doc.status.value,
                    "sizeBytes": doc.size_bytes,
                    "indexedAt": doc.indexed_at,
                    "lastError": doc.last_error,
                }
                for doc in docs
            ],
            "limit": limit,
            "offset": offset,
            "total": total,
        }

    async def list_jobs(self, *, limit: int = 20) -> dict[str, Any]:
        self._require_enabled()
        return {
            "kind": "jobs",
            "items": [self._job_to_wire(job) for job in await self.store.recent_jobs(limit=limit)],
            "limit": limit,
        }

    async def list_errors(
        self,
        *,
        limit: int = 100,
        source_id: str | None = None,
    ) -> dict[str, Any]:
        self._require_enabled()
        return {
            "kind": "errors",
            "items": await self.store.list_errors(limit=limit, source_id=source_id),
            "limit": limit,
        }

    async def sync(
        self,
        *,
        collection_id: str | None = None,
        source_id: str | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        self._require_enabled()
        jobs = []
        if source_id:
            source = await self.store.get_source(validate_identifier(source_id, field="source_id"))
            if source is None:
                raise RagNotFoundError("RAG source not found", details={"sourceId": source_id})
            if collection_id and source.collection_id != collection_id:
                raise RagValidationError("source_id does not belong to collection_id")
            jobs.append(await self.ingestion.sync_source(source.source_id, force=force))
        else:
            sources = await self.store.list_sources(
                collection_id=collection_id,
                include_disabled=False,
            )
            for source in sources:
                jobs.append(await self.ingestion.sync_source(source.source_id, force=force))
        return {"jobs": [self._job_to_wire(job) for job in jobs]}

    async def search(self, request: RagSearchRequest) -> dict[str, Any]:
        self._require_enabled()
        payload = await self.retrieval.search(request)
        return {
            **payload,
            "results": [result_to_wire(result) for result in payload["results"]],
        }

    async def show(
        self,
        *,
        chunk_id: str | None = None,
        document_id: str | None = None,
        source_id: str | None = None,
        path: str | None = None,
        max_chars: int = 12000,
    ) -> dict[str, Any]:
        self._require_enabled()
        if chunk_id:
            hit = await self.store.get_chunk(chunk_id)
            if hit is None:
                raise RagNotFoundError("RAG chunk not found", details={"chunkId": chunk_id})
            content = hit.content
            citation = RagCitation(
                collection_id=hit.collection_id,
                source_id=hit.source_id,
                document_path=hit.relative_path,
                document_title=hit.title,
                line_start=hit.line_start,
                line_end=hit.line_end,
            )
            citation_preview = {
                "collectionId": hit.collection_id,
                "sourceId": hit.source_id,
                "path": hit.relative_path,
                "title": hit.title,
                "lineStart": hit.line_start,
                "lineEnd": hit.line_end,
            }
            document = {
                "documentId": hit.document_id,
                "path": hit.relative_path,
                "title": hit.title,
                "status": "active",
            }
        else:
            chunks = await self.store.get_document_chunks(
                document_id=document_id,
                source_id=source_id,
                relative_path=path,
            )
            if not chunks:
                raise RagNotFoundError("RAG document not found")
            first = chunks[0]
            content = "\n\n".join(chunk.content for chunk in chunks)
            citation = RagCitation(
                collection_id=first.collection_id,
                source_id=first.source_id,
                document_path=first.relative_path,
                document_title=first.title,
                line_start=first.line_start,
                line_end=chunks[-1].line_end,
            )
            citation_preview = {
                "collectionId": first.collection_id,
                "sourceId": first.source_id,
                "path": first.relative_path,
                "title": first.title,
                "lineStart": first.line_start,
                "lineEnd": chunks[-1].line_end,
            }
            document = {
                "documentId": first.document_id,
                "path": first.relative_path,
                "title": first.title,
                "status": "active",
            }
        truncated = False
        if len(content) > max_chars:
            content = content[:max_chars].rstrip() + "\n..."
            truncated = True
        return {
            "document": document,
            "content": content,
            "truncated": truncated,
            "sourceKind": "rag",
            "untrustedEvidence": True,
            "citation": {**citation_preview, **citation_to_wire(citation)},
        }

    async def disable_source(self, source_id: str) -> dict[str, Any]:
        self._require_enabled()
        source = await self.source_registry.disable_source(source_id)
        if source is None:
            raise RagNotFoundError("RAG source not found", details={"sourceId": source_id})
        return self._source_to_wire(source)

    async def enable_source(self, source_id: str) -> dict[str, Any]:
        self._require_enabled()
        source = await self.source_registry.enable_source(source_id)
        if source is None:
            raise RagNotFoundError("RAG source not found", details={"sourceId": source_id})
        return self._source_to_wire(source)

    async def remove_source(self, source_id: str, *, delete_index: bool = True) -> dict[str, Any]:
        self._require_enabled()
        source_id = validate_identifier(source_id, field="source_id")
        source = await self.store.get_source(source_id)
        if source is None:
            raise RagNotFoundError("RAG source not found", details={"sourceId": source_id})
        if not delete_index:
            raise RagValidationError("remove_source requires delete_index=true")
        removed = await self.store.delete_source(source_id)
        if source.mode is RagSourceMode.IMPORTED:
            self._remove_imported_source_files(source)
        return {
            "removed": removed,
            "sourceId": source_id,
            "collectionId": source.collection_id,
            "deletedIndex": True,
        }

    def _remove_imported_source_files(self, source: RagSource) -> None:
        imports_dir = (rag_state_dir(self.config) / "imports").resolve()
        files_path = Path(source.root_path).expanduser()
        try:
            source_root = files_path.resolve().parent
            source_root.relative_to(imports_dir)
        except (OSError, ValueError):
            return
        if source_root == imports_dir:
            return
        shutil.rmtree(source_root, ignore_errors=True)

    def _require_enabled(self) -> None:
        if not self.enabled:
            raise RagDisabledError()

    def _source_to_wire(self, source: RagSource) -> dict[str, Any]:
        return {
            "sourceId": source.source_id,
            "collectionId": source.collection_id,
            "mode": source.mode.value,
            "path": source.root_path,
            "name": source.display_name,
            "include": list(source.include),
            "exclude": list(source.exclude),
            "enabled": source.enabled,
            "status": source.status.value,
            "staleReason": source.stale_reason,
            "lastError": source.last_error,
            "lastScanStartedAt": source.last_scan_started_at,
            "lastScanFinishedAt": source.last_scan_finished_at,
            "lastSuccessfulScanAt": source.last_successful_scan_at,
            "lastIndexedAt": source.last_indexed_at,
        }

    def _job_to_wire(self, job: Any) -> dict[str, Any]:
        duration_ms = None
        if job.finished_at is not None:
            duration_ms = max(0, int((job.finished_at - job.started_at) * 1000))
        return {
            "jobId": job.job_id,
            "jobType": job.job_type,
            "collectionId": job.collection_id,
            "sourceId": job.source_id,
            "status": job.status.value,
            "scanId": job.scan_id,
            "startedAt": job.started_at,
            "finishedAt": job.finished_at,
            "durationMs": duration_ms,
            "filesSeen": job.files_seen,
            "filesIndexed": job.files_indexed,
            "filesSkipped": job.files_skipped,
            "filesFailed": job.files_failed,
            "chunksWritten": job.chunks_written,
            "embeddingsWritten": job.embeddings_written,
            "errorCode": job.error_code,
            "errorMessage": job.error_message,
            "metadata": job.metadata,
        }

    def _job_status_summary(self, jobs: list[dict[str, Any]]) -> dict[str, int]:
        summary = {
            "pending": 0,
            "running": 0,
            "succeeded": 0,
            "partial": 0,
            "failed": 0,
            "canceled": 0,
        }
        for job in jobs:
            status = str(job.get("status") or "")
            if status in summary:
                summary[status] += 1
        return summary


async def build_rag_manager(config: GatewayConfig) -> RagManager | None:
    if not config.rag.enabled:
        return None
    embedding_decision = resolve_rag_embedding(config)
    embedding_provider = (
        create_rag_embedding_provider(config) if embedding_decision.enabled else None
    )
    store = RagStore(rag_db_path(config))
    await store.initialize(vector_dimensions=embedding_decision.dimensions)
    source_registry = SourceRegistry(store)
    await store.ensure_default_collection()
    ingestion = IngestionService(
        store=store,
        config=config.rag,
        embedding_provider=embedding_provider,
        embedding_fingerprint=embedding_decision.fingerprint,
        embedding_base_url=embedding_decision.base_url,
    )
    retrieval = RetrievalService(
        store=store,
        config=config.rag,
        embedding_provider=embedding_provider,
        embedding_reason=embedding_decision.reason,
    )
    manager = RagManager(
        config=config,
        store=store,
        source_registry=source_registry,
        ingestion=ingestion,
        retrieval=retrieval,
        embedding_decision=embedding_decision,
    )
    for source in config.rag.sources:
        await manager.add_source(
            path=source.path,
            collection_id=source.collection_id,
            source_id=source.source_id,
            name=source.name,
            include=source.include,
            exclude=source.exclude,
            enabled=source.enabled,
            index=False,
        )
    return manager
