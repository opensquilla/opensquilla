"""Retrieval service for FTS, vector and hybrid local RAG search."""

from __future__ import annotations

import re
import time
from collections.abc import Sequence
from typing import Any

from opensquilla.gateway.config import RagConfig
from opensquilla.memory.embedding import EmbeddingProvider

from .errors import RagEmbeddingError, RagValidationError
from .paths import normalize_relative_path
from .store import RagStore
from .types import (
    RagCitation,
    RagRawHit,
    RagRetrievalMode,
    RagSearchRequest,
    RagSearchResult,
)

_TOKEN_RE = re.compile(r"[\w\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+", re.UNICODE)


def build_fts_query(query: str) -> str:
    tokens = _TOKEN_RE.findall(query.strip())
    if not tokens:
        raise RagValidationError("RAG search query must contain searchable text")
    return " ".join(f'"{token}"' for token in tokens[:16])


def _snippet(content: str, query: str, *, max_chars: int = 500) -> str:
    text = " ".join(content.split())
    if len(text) <= max_chars:
        return text
    lowered = text.lower()
    first_token = next(iter(_TOKEN_RE.findall(query.lower())), "")
    idx = lowered.find(first_token) if first_token else -1
    start = max(0, idx - max_chars // 3) if idx >= 0 else 0
    return text[start : start + max_chars].strip() + "..."


def _hybrid_formula() -> str:
    return "score = textWeight * textScore + vectorWeight * vectorScore"


class RetrievalService:
    def __init__(
        self,
        *,
        store: RagStore,
        config: RagConfig,
        embedding_provider: EmbeddingProvider | None = None,
        embedding_reason: str | None = None,
    ) -> None:
        self.store = store
        self.config = config
        self.embedding_provider = embedding_provider
        self.embedding_reason = embedding_reason

    async def search(self, request: RagSearchRequest) -> dict[str, Any]:
        started = time.perf_counter()
        query = request.query.strip()
        if not query:
            raise RagValidationError("RAG search query must not be empty")
        mode = request.mode or RagRetrievalMode(self.config.retrieval_mode)
        limit = request.limit or self.config.search_limit_default
        limit = max(1, min(limit, self.config.search_limit_max))
        min_score = (
            self.config.min_score_default
            if request.min_score is None
            else request.min_score
        )
        if min_score < 0 or min_score > 1:
            raise RagValidationError("min_score must be between 0 and 1")
        path_prefix = (
            normalize_relative_path(request.path_prefix, field="path_prefix")
            if request.path_prefix
            else None
        )
        fallback: dict[str, Any] | None = None
        candidate_counts = {"fts": 0, "vector": 0, "merged": 0}
        if mode is RagRetrievalMode.FTS:
            hits = await self._search_fts(query, request, path_prefix, limit)
            candidate_counts["fts"] = len(hits)
            candidate_counts["merged"] = len(hits)
            effective_mode = "fts"
        elif mode is RagRetrievalMode.VECTOR_ONLY:
            hits = await self._search_vector_or_fail(query, request, path_prefix, limit)
            candidate_counts["vector"] = len(hits)
            candidate_counts["merged"] = len(hits)
            effective_mode = "vector_only"
        else:
            fts_hits = await self._search_fts(query, request, path_prefix, limit * 3)
            try:
                vector_hits = await self._search_vector_or_fail(
                    query,
                    request,
                    path_prefix,
                    limit * 3,
                )
                hits = self._merge_hybrid(fts_hits, vector_hits)
                candidate_counts = {
                    "fts": len(fts_hits),
                    "vector": len(vector_hits),
                    "merged": len(hits),
                }
                effective_mode = "hybrid"
            except RagEmbeddingError as exc:
                hits = fts_hits
                candidate_counts = {
                    "fts": len(fts_hits),
                    "vector": 0,
                    "merged": len(hits),
                }
                effective_mode = "fts"
                fallback = {"from": "hybrid", "to": "fts", "reason": exc.code}
        results = [
            result
            for result in self._to_results(hits, query=query, retrieval_mode=effective_mode)
            if result.score >= float(min_score)
        ][:limit]
        return {
            "query": query,
            "mode": mode.value,
            "effectiveMode": effective_mode,
            "results": results,
            "fallback": fallback,
            "diagnostics": {
                "durationMs": int((time.perf_counter() - started) * 1000),
                "resultCount": len(results),
                "candidates": {**candidate_counts, "returned": len(results)},
                "scoring": self._scoring_diagnostics(effective_mode),
            },
        }

    async def _search_fts(
        self,
        query: str,
        request: RagSearchRequest,
        path_prefix: str | None,
        limit: int,
    ) -> list[RagRawHit]:
        return await self.store.search_fts(
            build_fts_query(query),
            collection_id=request.collection_id,
            source_id=request.source_id,
            path_prefix=path_prefix,
            limit=limit,
        )

    async def _search_vector_or_fail(
        self,
        query: str,
        request: RagSearchRequest,
        path_prefix: str | None,
        limit: int,
    ) -> list[RagRawHit]:
        if self.embedding_provider is None:
            raise RagEmbeddingError(
                "embedding_unavailable",
                "RAG embedding provider is unavailable",
                details={"reason": self.embedding_reason},
            )
        if not self.store.vec_available:
            raise RagEmbeddingError("sqlite_vec_unavailable", "sqlite-vec is unavailable")
        embedding = await self.embedding_provider.embed_query(query)
        return await self.store.search_vector(
            embedding,
            collection_id=request.collection_id,
            source_id=request.source_id,
            path_prefix=path_prefix,
            limit=limit,
        )

    def _merge_hybrid(
        self,
        fts_hits: Sequence[RagRawHit],
        vector_hits: Sequence[RagRawHit],
    ) -> list[RagRawHit]:
        merged: dict[str, RagRawHit] = {}
        for hit in fts_hits:
            merged[hit.chunk_id] = hit
        for hit in vector_hits:
            existing = merged.get(hit.chunk_id)
            if existing is None:
                merged[hit.chunk_id] = hit
                continue
            existing.vector_score = hit.vector_score
        text_weight = self.config.text_weight
        vector_weight = self.config.vector_weight

        def score(hit: RagRawHit) -> float:
            return (text_weight * (hit.text_score or 0.0)) + (
                vector_weight * (hit.vector_score or 0.0)
            )

        return sorted(
            merged.values(),
            key=lambda hit: (-score(hit), hit.relative_path, hit.chunk_index),
        )

    def _to_results(
        self,
        hits: Sequence[RagRawHit],
        *,
        query: str,
        retrieval_mode: str,
    ) -> list[RagSearchResult]:
        results: list[RagSearchResult] = []
        for hit in hits:
            if retrieval_mode == "hybrid":
                score = (self.config.text_weight * (hit.text_score or 0.0)) + (
                    self.config.vector_weight * (hit.vector_score or 0.0)
                )
            elif retrieval_mode == "vector_only":
                score = hit.vector_score or 0.0
            else:
                score = hit.text_score or 0.0
            citation = RagCitation(
                collection_id=hit.collection_id,
                source_id=hit.source_id,
                document_path=hit.relative_path,
                document_title=hit.title,
                line_start=hit.line_start,
                line_end=hit.line_end,
            )
            results.append(
                RagSearchResult(
                    chunk_id=hit.chunk_id,
                    document_id=hit.document_id,
                    collection_id=hit.collection_id,
                    source_id=hit.source_id,
                    document_path=hit.relative_path,
                    title=hit.title,
                    content=hit.content,
                    snippet=_snippet(hit.content, query),
                    score=score,
                    text_score=hit.text_score,
                    vector_score=hit.vector_score,
                    retrieval_mode=retrieval_mode,
                    source_kind="rag",
                    source_status=hit.source_status,
                    citation=citation,
                    metadata={
                        "untrustedEvidence": True,
                        "scoreBreakdown": self._score_breakdown(
                            result_score=score,
                            text_score=hit.text_score,
                            vector_score=hit.vector_score,
                            retrieval_mode=retrieval_mode,
                        ),
                    },
                )
            )
        return results

    def _scoring_diagnostics(self, retrieval_mode: str) -> dict[str, Any]:
        if retrieval_mode == "hybrid":
            return {
                "strategy": "weighted_sum",
                "textWeight": self.config.text_weight,
                "vectorWeight": self.config.vector_weight,
                "formula": _hybrid_formula(),
            }
        if retrieval_mode == "vector_only":
            return {
                "strategy": "vector_score",
                "textWeight": 0.0,
                "vectorWeight": 1.0,
                "formula": "score = vectorScore",
            }
        return {
            "strategy": "text_score",
            "textWeight": 1.0,
            "vectorWeight": 0.0,
            "formula": "score = textScore",
        }

    def _score_breakdown(
        self,
        *,
        result_score: float,
        text_score: float | None,
        vector_score: float | None,
        retrieval_mode: str,
    ) -> dict[str, Any]:
        diagnostics = self._scoring_diagnostics(retrieval_mode)
        text_weight = float(diagnostics["textWeight"])
        vector_weight = float(diagnostics["vectorWeight"])
        fts_score = text_score or 0.0
        fts_contribution = text_weight * fts_score
        vector_contribution = vector_weight * (vector_score or 0.0)
        return {
            **diagnostics,
            "score": result_score,
            "ftsScore": fts_score,
            "textScore": text_score,
            "vectorScore": vector_score,
            "ftsContribution": fts_contribution,
            "textContribution": fts_contribution,
            "vectorContribution": vector_contribution,
        }
