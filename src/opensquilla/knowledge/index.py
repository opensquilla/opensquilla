from __future__ import annotations

import re
import sqlite3
from collections.abc import Sequence
from hashlib import sha256
from pathlib import Path
from typing import Any

from opensquilla.knowledge.models import KnowledgeChunk, KnowledgeDocument, KnowledgeSearchResult

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


class KnowledgeIndex:
    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS knowledge_documents (
                    doc_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    source TEXT NOT NULL,
                    source_path TEXT NOT NULL,
                    file_type TEXT NOT NULL,
                    content_kind TEXT NOT NULL,
                    date TEXT,
                    language_bucket TEXT NOT NULL,
                    pair_id TEXT,
                    content_sha256 TEXT
                );
                CREATE TABLE IF NOT EXISTS knowledge_chunks (
                    chunk_id TEXT PRIMARY KEY,
                    doc_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    title TEXT NOT NULL,
                    source TEXT NOT NULL,
                    source_path TEXT NOT NULL,
                    page_start INTEGER,
                    page_end INTEGER,
                    section TEXT,
                    language_bucket TEXT NOT NULL,
                    pair_id TEXT,
                    FOREIGN KEY(doc_id) REFERENCES knowledge_documents(doc_id)
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_chunks_fts
                USING fts5(chunk_id UNINDEXED, search_text);
                """
            )

    def reset(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                DELETE FROM knowledge_chunks_fts;
                DELETE FROM knowledge_chunks;
                DELETE FROM knowledge_documents;
                """
            )

    def add_documents(
        self,
        documents: Sequence[KnowledgeDocument],
        chunks: Sequence[KnowledgeChunk],
    ) -> None:
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT OR REPLACE INTO knowledge_documents (
                    doc_id, title, source, source_path, file_type, content_kind,
                    date, language_bucket, pair_id, content_sha256
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        doc.doc_id,
                        doc.title,
                        doc.source,
                        doc.source_path,
                        doc.file_type,
                        doc.content_kind,
                        doc.date,
                        doc.language_bucket,
                        doc.pair_id,
                        doc.content_sha256,
                    )
                    for doc in documents
                ],
            )
            conn.executemany(
                """
                INSERT OR REPLACE INTO knowledge_chunks (
                    chunk_id, doc_id, ordinal, text, title, source, source_path,
                    page_start, page_end, section, language_bucket, pair_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        chunk.chunk_id,
                        chunk.doc_id,
                        chunk.ordinal,
                        chunk.text,
                        chunk.title,
                        chunk.source,
                        chunk.source_path,
                        chunk.page_start,
                        chunk.page_end,
                        chunk.section,
                        chunk.language_bucket,
                        chunk.pair_id,
                    )
                    for chunk in chunks
                ],
            )
            conn.executemany(
                "INSERT OR REPLACE INTO knowledge_chunks_fts (chunk_id, search_text) VALUES (?, ?)",
                [
                    (
                        chunk.chunk_id,
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
        where = []
        params: list[Any] = []
        if source := filters.get("source"):
            where.append("c.source = ?")
            params.append(str(source))
        if content_kind := filters.get("contentKind"):
            where.append("d.content_kind = ?")
            params.append(str(content_kind))
        where_sql = f" AND {' AND '.join(where)}" if where else ""

        with self._connect() as conn:
            rows: list[sqlite3.Row]
            if fts_query:
                rows = conn.execute(
                    f"""
                    SELECT c.*, d.content_kind, bm25(knowledge_chunks_fts) AS rank
                    FROM knowledge_chunks_fts
                    JOIN knowledge_chunks c ON c.chunk_id = knowledge_chunks_fts.chunk_id
                    JOIN knowledge_documents d ON d.doc_id = c.doc_id
                    WHERE knowledge_chunks_fts MATCH ? {where_sql}
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
                    FROM knowledge_chunks c
                    JOIN knowledge_documents d ON d.doc_id = c.doc_id
                    WHERE c.text LIKE ? {where_sql}
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
            # SQLite FTS5 BM25 ranks are ordered ascending and are often
            # negative. Expose a positive lexical score for scanning, while
            # preserving the raw BM25 rank for debugging and evaluation.
            score = round(max(-rank, 0.0), 4)
            position = len(results) + 1
            results.append(
                KnowledgeSearchResult(
                    evidence_id=f"ev_{position:03d}",
                    document_id=str(row["doc_id"]),
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
                    SELECT c.*, d.content_kind, d.date
                    FROM knowledge_chunks c
                    JOIN knowledge_documents d ON d.doc_id = c.doc_id
                    WHERE c.chunk_id = ?
                    """,
                    (chunk_id,),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT c.*, d.content_kind, d.date
                    FROM knowledge_chunks c
                    JOIN knowledge_documents d ON d.doc_id = c.doc_id
                    WHERE c.doc_id = ?
                    ORDER BY c.ordinal ASC
                    LIMIT 1
                    """,
                    (document_id,),
                ).fetchone()
        if row is None:
            return None
        return {
            "chunkId": row["chunk_id"],
            "documentId": row["doc_id"],
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
        }

    def stats(self) -> dict[str, Any]:
        self.initialize()
        with self._connect() as conn:
            docs = conn.execute("SELECT COUNT(*) FROM knowledge_documents").fetchone()[0]
            chunks = conn.execute("SELECT COUNT(*) FROM knowledge_chunks").fetchone()[0]
            sources = conn.execute(
                "SELECT source, COUNT(*) AS count FROM knowledge_documents GROUP BY source"
            ).fetchall()
        return {
            "documentsIndexed": int(docs),
            "chunksIndexed": int(chunks),
            "sources": [{"source": row["source"], "count": int(row["count"])} for row in sources],
            "dbPath": str(self.db_path),
        }

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
