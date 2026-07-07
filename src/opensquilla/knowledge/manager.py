from __future__ import annotations

import csv
import json
import re
import time
from pathlib import Path
from typing import Any

from opensquilla.knowledge.chunking import chunk_text, detect_language_bucket
from opensquilla.knowledge.index import KnowledgeIndex
from opensquilla.knowledge.models import KnowledgeChunk, KnowledgeDocument
from opensquilla.knowledge.parsers import content_sha256, parse_document

_SUPPORTED_EXTENSIONS = {".md", ".markdown", ".txt", ".pdf"}
_DEFAULT_SOURCE_ROOT = Path("/Users/chengsiyang/Downloads/研报")


class KnowledgeManager:
    def __init__(self, root_dir: Path | str) -> None:
        self.root_dir = Path(root_dir)
        self.data_dir = self.root_dir / "data"
        self.normalized_dir = self.data_dir / "normalized"
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
            **stats,
        }

    def prepare_sample(
        self,
        *,
        source_root: Path | str | None = None,
        limit: int = 60,
    ) -> dict[str, Any]:
        self._ensure_dirs()
        source_root_path = Path(source_root) if source_root else _DEFAULT_SOURCE_ROOT
        files = self._select_sample_files(source_root_path, limit=max(1, min(int(limit), 120)))
        documents: list[KnowledgeDocument] = []
        chunks: list[KnowledgeChunk] = []
        parser_rows: list[dict[str, Any]] = []

        for path in files:
            relative_path = _relative_to(path, source_root_path)
            try:
                parsed = parse_document(path)
                sha = content_sha256(path)
                doc_id = f"doc_{sha[:16]}"
                title = parsed.title or path.stem
                language = detect_language_bucket(parsed.text or title)
                source = relative_path.parts[0] if len(relative_path.parts) > 1 else "local"
                content_kind = _content_kind(relative_path)
                pair_id = _pair_id(relative_path)
                doc = KnowledgeDocument(
                    doc_id=doc_id,
                    title=title,
                    source=source,
                    source_path=str(relative_path),
                    file_type=path.suffix.lower(),
                    content_kind=content_kind,
                    date=_leading_date(path.name),
                    language_bucket=language,
                    pair_id=pair_id,
                    content_sha256=sha,
                )
                doc_chunks = chunk_text(
                    parsed.text,
                    doc_id=doc_id,
                    title=title,
                    source_path=str(relative_path),
                    source=source,
                    page_start=1,
                    pair_id=pair_id,
                )
                if parsed.status != "ready" or not doc_chunks:
                    parser_rows.append(
                        {
                            "path": str(relative_path),
                            "status": parsed.status,
                            "parser": parsed.parser,
                            "chunks": 0,
                            "error": parsed.error or "no text extracted",
                        }
                    )
                    continue
                documents.append(doc)
                chunks.extend(doc_chunks)
                self._write_json(
                    self.normalized_dir / f"{doc_id}.json",
                    {"document": doc.to_json(), "text": parsed.text},
                )
                parser_rows.append(
                    {
                        "path": str(relative_path),
                        "status": parsed.status,
                        "parser": parsed.parser,
                        "chunks": len(doc_chunks),
                        "error": parsed.error,
                    }
                )
            except Exception as exc:  # noqa: BLE001 - report individual bad documents
                parser_rows.append(
                    {
                        "path": str(relative_path),
                        "status": "error",
                        "parser": "unknown",
                        "chunks": 0,
                        "error": str(exc),
                    }
                )

        self.index.initialize()
        self.index.reset()
        self.index.add_documents(documents, chunks)
        self._write_jsonl(
            self.data_dir / "sample_manifest.jsonl",
            [doc.to_json() for doc in documents],
        )
        self._write_jsonl(self.chunks_dir / "chunks.jsonl", [chunk.to_json() for chunk in chunks])
        questions = self._build_questions(documents, chunks)
        self._write_jsonl(self.eval_dir / "golden_queries.jsonl", questions)
        self._write_parser_report(source_root_path, parser_rows, len(documents), len(chunks))
        return {
            "ok": True,
            "sourceRoot": str(source_root_path),
            "documentsSelected": len(files),
            "documentsIndexed": len(documents),
            "chunksIndexed": len(chunks),
            "questions": len(questions),
            "parserErrors": len([row for row in parser_rows if row["status"] == "error"]),
            "lowText": len([row for row in parser_rows if row["status"] == "low_text"]),
            "rootDir": str(self.root_dir),
        }

    def search(
        self,
        query: str,
        *,
        top_k: int = 8,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        results = self.index.search(query, top_k=top_k, filters=filters)
        return {
            "query": query,
            "retrieval": "sqlite_fts5",
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
            "results": payload.get("results") or [],
        }
        path = self.eval_dir / "judgments.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        return {"ok": True, "path": str(path), "judgment": row}

    def _ensure_dirs(self) -> None:
        for path in (
            self.data_dir,
            self.normalized_dir,
            self.chunks_dir,
            self.eval_dir,
            self.reports_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def _select_sample_files(self, source_root: Path, *, limit: int) -> list[Path]:
        inventory = source_root / "_rag_analysis" / "canonical_file_inventory.csv"
        if inventory.exists():
            rows = _read_inventory(inventory, source_root)
            chosen: list[Path] = []
            by_ext = {
                ".md": [
                    path
                    for path in rows
                    if path.suffix.lower() in {".md", ".markdown", ".txt"}
                ],
                ".pdf": [path for path in rows if path.suffix.lower() == ".pdf"],
            }
            md_limit = max(1, int(limit * 0.65))
            targets = [(".md", md_limit), (".pdf", max(1, limit - md_limit))]
            for ext, cap in targets:
                for path in by_ext.get(ext, [])[:cap]:
                    if path.exists() and path not in chosen:
                        chosen.append(path)
            if len(chosen) < limit:
                for path in rows:
                    if (
                        path.exists()
                        and path.suffix.lower() in _SUPPORTED_EXTENSIONS
                        and path not in chosen
                    ):
                        chosen.append(path)
                    if len(chosen) >= limit:
                        break
            return chosen[:limit]

        files = [
            path
            for path in source_root.rglob("*")
            if path.is_file() and path.suffix.lower() in _SUPPORTED_EXTENSIONS
        ]
        files.sort(key=lambda p: (p.suffix.lower() != ".md", len(str(p)), str(p)))
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
                f"| {row['path']} | {row['status']} | {row['parser']} | "
                f"{row['chunks']} | {row.get('error') or ''} |"
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
    rows.sort(key=lambda path: (path.suffix.lower() == ".pdf", str(path)))
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
