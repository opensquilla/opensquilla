from __future__ import annotations

import csv
import json
import re
import time
import zipfile
from pathlib import Path
from typing import Any

from opensquilla.knowledge.chunking import chunk_text, detect_language_bucket
from opensquilla.knowledge.index import KnowledgeIndex
from opensquilla.knowledge.models import (
    ArtifactRecord,
    ChunkLineage,
    IndexBuildRecord,
    KnowledgeChunk,
    KnowledgeCollection,
    KnowledgeDocument,
    SourceSnapshot,
)
from opensquilla.knowledge.parsers import text_sha256
from opensquilla.knowledge.pipeline import (
    DEFAULT_INDEX_PROFILES,
    analyze_source_file,
    build_processing_plan,
    make_collection_id,
    make_stable_id,
    parse_with_plan,
)

_SUPPORTED_EXTENSIONS = {".md", ".markdown", ".txt", ".html", ".htm", ".pdf"}
_DEFAULT_SOURCE_ROOT = Path("/mnt/data/datasets")


class KnowledgeManager:
    def __init__(self, root_dir: Path | str) -> None:
        self.root_dir = Path(root_dir)
        self.data_dir = self.root_dir / "data"
        self.normalized_dir = self.data_dir / "normalized"
        self.artifacts_dir = self.data_dir / "artifacts"
        self.imports_dir = self.data_dir / "imports"
        self.chunks_dir = self.data_dir / "chunks"
        self.eval_dir = self.data_dir / "eval"
        self.reports_dir = self.root_dir / "reports"
        self.index = KnowledgeIndex(self.root_dir / "knowledge.db")

    def status(self) -> dict[str, Any]:
        self._ensure_dirs()
        stats = self.index.stats()
        return {
            "ok": True,
            "rootDir": str(self.root_dir),
            "dataDir": str(self.data_dir),
            "manifestPath": str(self.data_dir / "sample_manifest.jsonl"),
            "questionsPath": str(self.eval_dir / "golden_queries.jsonl"),
            "pipeline": "analyze-plan-execute-trace",
            "defaultSourceRoot": str(_DEFAULT_SOURCE_ROOT),
            **stats,
        }

    def collections(self) -> dict[str, Any]:
        return {"collections": self.index.list_collections()}

    def prepare_sample(
        self,
        *,
        source_root: Path | str | None = None,
        limit: int = 60,
        collection_name: str | None = None,
    ) -> dict[str, Any]:
        return self.ingest_collection(
            source_root=source_root,
            limit=limit,
            collection_name=collection_name or "default",
            collection_id="default",
        )

    def ingest_collection(
        self,
        *,
        source_root: Path | str | None = None,
        limit: int = 60,
        collection_name: str | None = None,
        collection_id: str | None = None,
        index_profiles: list[str] | None = None,
    ) -> dict[str, Any]:
        self._ensure_dirs()
        start = int(time.time() * 1000)
        source_root_path = Path(source_root) if source_root else _DEFAULT_SOURCE_ROOT
        resolved_root = self._resolve_source_root(source_root_path)
        name = collection_name or resolved_root.name or "default"
        cid = collection_id or make_collection_id(name)
        profiles = index_profiles or DEFAULT_INDEX_PROFILES
        files = self._select_sample_files(resolved_root, limit=max(1, min(int(limit), 500)))
        source_uri = str(source_root_path)
        snapshot_id = make_stable_id("snap", cid, source_uri, str(start))
        job_id = make_stable_id("job", cid, source_uri, str(start))

        collection = KnowledgeCollection(
            collection_id=cid,
            name=name,
            source_uri=source_uri,
            created_at=start,
            updated_at=start,
            config={
                "pipeline": "analyze-plan-execute-trace",
                "indexProfiles": profiles,
                "sourceRoot": str(source_root_path),
                "resolvedRoot": str(resolved_root),
            },
        )
        snapshot = SourceSnapshot(
            snapshot_id=snapshot_id,
            collection_id=cid,
            source_uri=source_uri,
            snapshot_kind="zip" if source_root_path.suffix.lower() == ".zip" else "directory",
            created_at=start,
            metadata={"limit": limit, "resolvedRoot": str(resolved_root)},
        )

        source_files = []
        profiles_out = []
        plans = []
        artifacts: list[ArtifactRecord] = []
        documents: list[KnowledgeDocument] = []
        chunks: list[KnowledgeChunk] = []
        lineages: list[ChunkLineage] = []
        manifest_entries: list[dict[str, Any]] = []
        parser_rows: list[dict[str, Any]] = []

        for path in files:
            source_file = None
            relative_path = _relative_to(path, resolved_root)
            now = int(time.time() * 1000)
            try:
                source_file, profile = analyze_source_file(
                    path,
                    root=resolved_root,
                    collection_id=cid,
                    snapshot_id=snapshot_id,
                )
                plan = build_processing_plan(source_file, profile, index_profiles=profiles)
                source_files.append(source_file)
                profiles_out.append(profile)
                plans.append(plan)
                if plan.status == "unsupported":
                    raise ValueError(f"Unsupported knowledge file type: {path.suffix or '<none>'}")

                parsed = parse_with_plan(path, plan)
                if parsed.status != "ready" or not parsed.text.strip():
                    parser_rows.append(
                        _parser_row(relative_path, parsed.status, parsed.parser, 0, parsed.error)
                    )
                    manifest_entries.append(
                        _manifest_entry(
                            cid,
                            source_file.source_file_id,
                            None,
                            "skipped",
                            parsed.error or parsed.status,
                            now,
                        )
                    )
                    continue

                doc_id = make_stable_id(
                    "doc", cid, source_file.source_path, source_file.content_sha256
                )
                artifact = self._write_normalized_artifact(
                    collection_id=cid,
                    source_file_id=source_file.source_file_id,
                    document_id=doc_id,
                    strategy=plan.preprocessor_strategy,
                    parsed_title=parsed.title,
                    text=parsed.text,
                    metadata={
                        "parser": parsed.parser,
                        "status": parsed.status,
                        "pageCount": parsed.page_count,
                        **parsed.metadata,
                    },
                )
                artifacts.append(artifact)

                title = parsed.title or path.stem
                language = detect_language_bucket(parsed.text or title)
                source = relative_path.parts[0] if len(relative_path.parts) > 1 else "local"
                content_kind = _content_kind(relative_path)
                pair_id = _pair_id(relative_path)
                document = KnowledgeDocument(
                    doc_id=doc_id,
                    collection_id=cid,
                    source_file_id=source_file.source_file_id,
                    profile_id=profile.profile_id,
                    plan_id=plan.plan_id,
                    title=title,
                    source=source,
                    source_path=str(relative_path),
                    file_type=path.suffix.lower(),
                    content_kind=content_kind,
                    date=_leading_date(path.name),
                    language_bucket=language,
                    pair_id=pair_id,
                    content_sha256=source_file.content_sha256,
                    parser=parsed.parser,
                    metadata={
                        "pageCount": parsed.page_count,
                        "artifactId": artifact.artifact_id,
                        "profileId": profile.profile_id,
                        "planId": plan.plan_id,
                    },
                )
                doc_chunks = chunk_text(
                    parsed.text,
                    doc_id=doc_id,
                    title=title,
                    source_path=str(relative_path),
                    source=source,
                    page_start=1,
                    pair_id=pair_id,
                    collection_id=cid,
                    source_file_id=source_file.source_file_id,
                    artifact_id=artifact.artifact_id,
                    plan_id=plan.plan_id,
                    strategy=plan.chunking_strategy,
                    metadata={"planId": plan.plan_id, "artifactId": artifact.artifact_id},
                )
                doc_chunks = _with_char_offsets(doc_chunks, parsed.text)
                if not doc_chunks:
                    parser_rows.append(
                        _parser_row(relative_path, "low_text", parsed.parser, 0, "no chunks")
                    )
                    manifest_entries.append(
                        _manifest_entry(
                            cid,
                            source_file.source_file_id,
                            doc_id,
                            "skipped",
                            "no chunks",
                            now,
                        )
                    )
                    continue

                documents.append(document)
                chunks.extend(doc_chunks)
                lineages.extend(
                    _lineage_for_chunks(
                        doc_chunks,
                        document=document,
                        artifact=artifact,
                        plan_id=plan.plan_id,
                        preprocessor_strategy=plan.preprocessor_strategy,
                        chunking_strategy=plan.chunking_strategy,
                    )
                )
                manifest_entries.append(
                    _manifest_entry(
                        cid,
                        source_file.source_file_id,
                        doc_id,
                        "ready",
                        None,
                        now,
                        {"chunks": len(doc_chunks), "parser": parsed.parser},
                    )
                )
                self._write_json(
                    self.normalized_dir / f"{doc_id}.json",
                    {"document": document.to_json(), "text": parsed.text},
                )
                parser_rows.append(
                    _parser_row(
                        relative_path,
                        parsed.status,
                        parsed.parser,
                        len(doc_chunks),
                        parsed.error,
                    )
                )
            except Exception as exc:  # noqa: BLE001 - report individual bad documents
                parser_rows.append(_parser_row(relative_path, "error", "unknown", 0, str(exc)))
                if source_file is not None:
                    manifest_entries.append(
                        _manifest_entry(
                            cid,
                            source_file.source_file_id,
                            None,
                            "error",
                            str(exc),
                            now,
                        )
                    )

        finished = int(time.time() * 1000)
        index_build = IndexBuildRecord(
            build_id=make_stable_id("idx", cid, ",".join(profiles), str(finished)),
            collection_id=cid,
            profile_id="sqlite_fts5_default",
            index_type="sqlite_fts5",
            status="ready",
            documents_indexed=len(documents),
            chunks_indexed=len(chunks),
            created_at=start,
            completed_at=finished,
            metadata={"profiles": profiles},
        )
        ingest_job = {
            "job_id": job_id,
            "collection_id": cid,
            "source_uri": source_uri,
            "status": "ready",
            "started_at": start,
            "finished_at": finished,
            "files_seen": len(files),
            "files_ready": len(documents),
            "files_failed": len([row for row in parser_rows if row["status"] == "error"]),
            "documents_indexed": len(documents),
            "chunks_indexed": len(chunks),
            "config": {"limit": limit, "indexProfiles": profiles},
        }

        self.index.replace_collection_records(
            collection=collection,
            snapshot=snapshot,
            source_files=source_files,
            profiles=profiles_out,
            plans=plans,
            artifacts=artifacts,
            documents=documents,
            chunks=chunks,
            lineages=lineages,
            manifest_entries=manifest_entries,
            ingest_job=ingest_job,
            index_builds=[index_build],
        )
        self._write_jsonl(
            self.data_dir / "sample_manifest.jsonl",
            [entry for entry in manifest_entries],
        )
        self._write_jsonl(self.chunks_dir / "chunks.jsonl", [chunk.to_json() for chunk in chunks])
        questions = self._build_questions(documents, chunks)
        self._write_jsonl(self.eval_dir / "golden_queries.jsonl", questions)
        self._write_parser_report(resolved_root, parser_rows, len(documents), len(chunks))
        return {
            "ok": True,
            "collectionId": cid,
            "collectionName": name,
            "sourceRoot": str(source_root_path),
            "resolvedRoot": str(resolved_root),
            "documentsSelected": len(files),
            "documentsIndexed": len(documents),
            "chunksIndexed": len(chunks),
            "questions": len(questions),
            "parserErrors": len([row for row in parser_rows if row["status"] == "error"]),
            "lowText": len([row for row in parser_rows if row["status"] == "low_text"]),
            "rootDir": str(self.root_dir),
            "indexProfiles": profiles,
        }

    def search(
        self,
        query: str,
        *,
        top_k: int = 8,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        results = self.index.search(query, top_k=top_k, filters=filters)
        retrieval = str((filters or {}).get("retrievalProfile") or "sqlite_fts5_default")
        return {
            "query": query,
            "retrieval": retrieval,
            "results": [result.to_wire() for result in results],
            "count": len(results),
        }

    def get(
        self,
        *,
        chunk_id: str | None = None,
        document_id: str | None = None,
    ) -> dict[str, Any] | None:
        return self.index.get(chunk_id=chunk_id, document_id=document_id)

    def questions(self) -> dict[str, Any]:
        path = self.eval_dir / "golden_queries.jsonl"
        if not path.exists():
            return {"questions": [], "path": str(path)}
        rows = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        return {"questions": rows, "path": str(path), "count": len(rows)}

    def record_judgment(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._ensure_dirs()
        row = {
            "createdAt": int(time.time() * 1000),
            "questionId": str(payload.get("questionId") or ""),
            "question": str(payload.get("question") or ""),
            "rating": str(payload.get("rating") or ""),
            "evidence": str(payload.get("evidence") or ""),
            "hallucination": str(payload.get("hallucination") or ""),
            "notes": str(payload.get("notes") or ""),
            "selectedChunkId": payload.get("selectedChunkId"),
            "collectionId": payload.get("collectionId") or "default",
            "results": payload.get("results") or [],
        }
        path = self.eval_dir / "judgments.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        self.index.record_judgment(row)
        return {"ok": True, "path": str(path), "judgment": row}

    def _ensure_dirs(self) -> None:
        for path in (
            self.data_dir,
            self.normalized_dir,
            self.artifacts_dir,
            self.imports_dir,
            self.chunks_dir,
            self.eval_dir,
            self.reports_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def _resolve_source_root(self, source_root: Path) -> Path:
        if source_root.suffix.lower() == ".zip" and source_root.is_file():
            target = self.imports_dir / f"{source_root.stem}-{_file_digest_short(source_root)}"
            target.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(source_root) as archive:
                for member in archive.infolist():
                    if member.is_dir():
                        continue
                    destination = _safe_zip_destination(target, member.filename)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(member) as src, destination.open("wb") as dst:
                        dst.write(src.read())
            return target
        return source_root

    def _select_sample_files(self, source_root: Path, *, limit: int) -> list[Path]:
        inventory = source_root / "_rag_analysis" / "canonical_file_inventory.csv"
        if inventory.exists():
            rows = _read_inventory(inventory, source_root)
            return rows[:limit]

        files = [
            path
            for path in source_root.rglob("*")
            if path.is_file() and path.suffix.lower() in _SUPPORTED_EXTENSIONS
        ]
        files.sort(key=lambda p: _file_sort_key(p, source_root))
        return files[:limit]

    def _build_questions(
        self,
        documents: list[KnowledgeDocument],
        chunks: list[KnowledgeChunk],
    ) -> list[dict[str, Any]]:
        questions: list[dict[str, Any]] = []
        by_doc = {doc.doc_id: doc for doc in documents}
        for chunk in chunks[:50]:
            doc = by_doc.get(chunk.doc_id)
            if doc is None:
                continue
            keyword = _question_keyword(chunk.text) or doc.title[:16]
            questions.append(
                {
                    "id": f"q{len(questions) + 1:03d}",
                    "question": f"根据资料库，{keyword}相关的核心观点是什么？",
                    "expectedDocIds": [doc.doc_id],
                    "expectedEvidenceHint": chunk.text[:160],
                    "answerType": "summary",
                    "sourcePath": doc.source_path,
                    "collectionId": doc.collection_id,
                }
            )
            if len(questions) >= 30:
                break
        questions.append(
            {
                "id": f"q{len(questions) + 1:03d}",
                "question": "资料库中是否有关于不存在公司XYZ-NotFound的明确结论？",
                "expectedDocIds": [],
                "expectedEvidenceHint": "应返回无可靠证据或检索为空。",
                "answerType": "not_found",
            }
        )
        return questions

    def _write_normalized_artifact(
        self,
        *,
        collection_id: str,
        source_file_id: str,
        document_id: str,
        strategy: str,
        parsed_title: str,
        text: str,
        metadata: dict[str, Any],
    ) -> ArtifactRecord:
        now = int(time.time() * 1000)
        content_hash = text_sha256(text)
        artifact_id = make_stable_id("art", document_id, strategy, content_hash)
        artifact_path = self.artifacts_dir / f"{artifact_id}.json"
        payload = {
            "artifactId": artifact_id,
            "collectionId": collection_id,
            "sourceFileId": source_file_id,
            "documentId": document_id,
            "strategy": strategy,
            "title": parsed_title,
            "text": text,
            "metadata": metadata,
        }
        self._write_json(artifact_path, payload)
        return ArtifactRecord(
            artifact_id=artifact_id,
            collection_id=collection_id,
            source_file_id=source_file_id,
            document_id=document_id,
            artifact_type="normalized_text",
            strategy=strategy,
            uri=str(artifact_path.relative_to(self.root_dir)),
            content_sha256=content_hash,
            size_bytes=artifact_path.stat().st_size,
            created_at=now,
            metadata=metadata,
        )

    def _write_parser_report(
        self,
        source_root: Path,
        rows: list[dict[str, Any]],
        documents_indexed: int,
        chunks_indexed: int,
    ) -> None:
        ok = len([row for row in rows if row["status"] == "ready"])
        errors = len([row for row in rows if row["status"] == "error"])
        low_text = len([row for row in rows if row["status"] == "low_text"])
        lines = [
            "# Phase 0 Parser Report",
            "",
            f"- Source root: `{source_root}`",
            f"- Files selected: `{len(rows)}`",
            f"- Ready files: `{ok}`",
            f"- Low text files: `{low_text}`",
            f"- Error files: `{errors}`",
            f"- Documents indexed: `{documents_indexed}`",
            f"- Chunks indexed: `{chunks_indexed}`",
            "",
            "## Files",
            "",
            "| Path | Status | Parser | Chunks | Error |",
            "| --- | --- | --- | ---: | --- |",
        ]
        for row in rows:
            lines.append(
                f"| {_escape_table(row['path'])} | {row['status']} | {row['parser']} | "
                f"{row['chunks']} | {_escape_table(row.get('error') or '')} |"
            )
        (self.reports_dir / "parser_report.md").write_text(
            "\n".join(lines) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def manager_from_config(config: Any | None) -> KnowledgeManager:
    state_dir = Path(str(getattr(config, "state_dir", "") or ".opensquilla"))
    return KnowledgeManager(state_dir / "knowledge")


def _read_inventory(inventory: Path, source_root: Path) -> list[Path]:
    rows: list[Path] = []
    with inventory.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if str(row.get("exists") or "").lower() not in {"yes", "true", "1"}:
                continue
            ext = str(row.get("extension") or "").lower()
            if ext not in _SUPPORTED_EXTENSIONS:
                continue
            rel = str(row.get("relative_path") or "")
            if not rel:
                continue
            rows.append(source_root / rel)
    rows.sort(key=lambda path: _file_sort_key(path, source_root))
    return rows


def _relative_to(path: Path, root: Path) -> Path:
    try:
        return path.relative_to(root)
    except ValueError:
        return Path(path.name)


def _leading_date(name: str) -> str | None:
    match = re.search(r"(20\d{2})[-_.年](\d{1,2})[-_.月](\d{1,2})", name)
    if not match:
        return None
    year, month, day = match.groups()
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"


def _content_kind(path: Path) -> str:
    text = str(path).lower()
    if "ai摘要" in str(path) or "summary" in text:
        return "ai_summary"
    if "原文" in str(path) or "transcript" in text:
        return "original_transcript"
    if path.suffix.lower() in {".html", ".htm"}:
        return "html_report"
    return "report"


def _pair_id(path: Path) -> str | None:
    text = str(path)
    if "AI摘要" in text:
        return text.replace("AI摘要", "").replace(path.suffix, "")
    if "原文" in text:
        return text.replace("原文", "").replace(path.suffix, "")
    return None


def _question_keyword(text: str) -> str | None:
    cleaned = re.sub(r"\s+", "", text)
    cjk = re.findall(r"[\u3400-\u9fff]{2,12}", cleaned)
    if cjk:
        return cjk[0][:12]
    words = re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", text)
    return " ".join(words[:3]) if words else None


def _file_sort_key(path: Path, root: Path) -> tuple[int, int, str]:
    suffix = path.suffix.lower()
    priority = (
        0
        if suffix in {".md", ".markdown"}
        else 1
        if suffix in {".html", ".htm", ".txt"}
        else 2
    )
    return (priority, len(str(_relative_to(path, root))), str(path))


def _parser_row(
    path: Path,
    status: str,
    parser: str,
    chunks: int,
    error: str | None,
) -> dict[str, Any]:
    return {
        "path": str(path),
        "status": status,
        "parser": parser,
        "chunks": chunks,
        "error": error,
    }


def _manifest_entry(
    collection_id: str,
    source_file_id: str,
    document_id: str | None,
    status: str,
    reason: str | None,
    created_at: int,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "manifest_id": make_stable_id(
            "man", collection_id, source_file_id, document_id or "", status
        ),
        "collection_id": collection_id,
        "source_file_id": source_file_id,
        "document_id": document_id,
        "status": status,
        "reason": reason,
        "metadata": metadata or {},
        "created_at": created_at,
    }


def _lineage_for_chunks(
    chunks: list[KnowledgeChunk],
    *,
    document: KnowledgeDocument,
    artifact: ArtifactRecord,
    plan_id: str,
    preprocessor_strategy: str,
    chunking_strategy: str,
) -> list[ChunkLineage]:
    now = int(time.time() * 1000)
    rows: list[ChunkLineage] = []
    for chunk in chunks:
        for step_ordinal, operation, params, input_ref, output_ref, reversible in (
            (
                1,
                "preprocess",
                {"strategy": preprocessor_strategy},
                document.source_path,
                artifact.artifact_id,
                True,
            ),
            (
                2,
                "chunk",
                {
                    "strategy": chunking_strategy,
                    "ordinal": chunk.ordinal,
                    "charStart": chunk.char_start,
                    "charEnd": chunk.char_end,
                },
                artifact.artifact_id,
                chunk.chunk_id,
                True,
            ),
            (
                3,
                "index",
                {"strategy": "sqlite_fts5_default"},
                chunk.chunk_id,
                "fts_chunks",
                False,
            ),
        ):
            rows.append(
                ChunkLineage(
                    lineage_id=make_stable_id(
                        "lin", chunk.chunk_id, str(step_ordinal), operation
                    ),
                    chunk_id=chunk.chunk_id,
                    document_id=document.doc_id,
                    source_file_id=document.source_file_id or "",
                    collection_id=document.collection_id,
                    artifact_id=artifact.artifact_id,
                    plan_id=plan_id,
                    step_ordinal=step_ordinal,
                    operation=operation,
                    params=params,
                    input_ref=input_ref,
                    output_ref=output_ref,
                    reversible=reversible,
                    created_at=now,
                )
            )
    return rows


def _with_char_offsets(chunks: list[KnowledgeChunk], text: str) -> list[KnowledgeChunk]:
    offset_chunks: list[KnowledgeChunk] = []
    cursor = 0
    for chunk in chunks:
        needle = chunk.text[: min(80, len(chunk.text))].strip()
        start = text.find(needle, cursor) if needle else -1
        if start < 0:
            start = text.find(needle) if needle else -1
        if start < 0:
            start = None
            end = None
        else:
            end = min(len(text), start + len(chunk.text))
            cursor = max(cursor, end - 120)
        payload = chunk.to_json()
        payload["char_start"] = start
        payload["char_end"] = end
        offset_chunks.append(KnowledgeChunk(**payload))
    return offset_chunks


def _safe_zip_destination(root: Path, member_name: str) -> Path:
    destination = (root / member_name).resolve()
    root_resolved = root.resolve()
    if root_resolved not in destination.parents and destination != root_resolved:
        raise ValueError(f"Unsafe zip member path: {member_name}")
    return destination


def _file_digest_short(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()[:12]


def _escape_table(value: str) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")
