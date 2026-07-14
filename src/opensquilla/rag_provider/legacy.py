from __future__ import annotations

import asyncio
import hashlib
from typing import Any

from opensquilla.rag_provider.protocol import (
    CapabilitiesSnapshot,
    EffectiveLimits,
    ProviderNotFound,
    ProviderProtocolViolation,
    ProviderUnavailable,
    SearchBudget,
    ValidatedSearchResponse,
    validate_search_response,
)

LEGACY_WARNING = (
    "LEGACY：正在使用旧版 OpenSquilla-Knowledge 接口，"
    "不具备完整协议保证和全文读取语义。"
)


class LegacyKnowledgeAdapter:
    """Explicit adapter for the pre-Provider KnowledgeBackend surface.

    Evidence mappings intentionally live only for this process.  This keeps
    the compatibility path honest: it does not claim stable Provider 1.0
    identities or full-text cursor semantics that the old backend cannot
    guarantee.
    """

    def __init__(self, backend: Any) -> None:
        self._backend = backend
        self._evidence: dict[str, tuple[str | None, str | None]] = {}

    async def capabilities(self) -> CapabilitiesSnapshot:
        return CapabilitiesSnapshot(
            protocol_version="legacy",
            provider_name="OpenSquilla legacy Knowledge adapter",
            provider_version="legacy",
            instance_id="legacy-process-local",
            supports_get=True,
            limits=EffectiveLimits(20, 800, 12_000, 8_000),
            supports_collection_scope=False,
            retrieval_profiles=(),
            default_retrieval_profile=None,
            management_url=None,
        )

    async def search(
        self,
        *,
        query: str,
        limit: int,
        budget: SearchBudget,
        collection_ids: tuple[str, ...] = (),
        retrieval_profile: str | None = None,
    ) -> ValidatedSearchResponse:
        filters = {"retrievalProfile": retrieval_profile} if retrieval_profile else None
        try:
            raw = await asyncio.to_thread(
                self._backend.search,
                query,
                top_k=limit,
                filters=filters,
            )
        except Exception as error:
            raise ProviderUnavailable("legacy knowledge backend is unavailable") from error
        raw_results = raw.get("results") if isinstance(raw, dict) else None
        if not isinstance(raw_results, list):
            raise ProviderProtocolViolation("legacy search results are invalid")
        results: list[dict[str, Any]] = []
        for item in raw_results:
            if not isinstance(item, dict):
                raise ProviderProtocolViolation("legacy search result is invalid")
            chunk_id = _optional_text(item.get("chunkId") or item.get("chunk_id"))
            document_id = _optional_text(
                item.get("documentId") or item.get("document_id")
            )
            if chunk_id is None and document_id is None:
                raise ProviderProtocolViolation("legacy result has no retrievable identity")
            evidence_id = _legacy_evidence_id(chunk_id, document_id)
            self._evidence[evidence_id] = (chunk_id, document_id)
            snippet = _optional_text(item.get("snippet") or item.get("text")) or ""
            title = _optional_text(item.get("title")) or document_id or chunk_id or "Evidence"
            source = _optional_text(item.get("source"))
            locator = _optional_text(item.get("citation") or item.get("sourcePath"))
            citation: dict[str, str] = {"title": title}
            if source:
                citation["source"] = source
            if locator:
                citation["locator"] = locator
            results.append(
                {
                    "evidenceId": evidence_id,
                    "snippet": snippet,
                    "snippetTruncated": False,
                    "citation": citation,
                }
            )
        raw_count = raw.get("count") if isinstance(raw, dict) else None
        total = (
            raw_count
            if isinstance(raw_count, int) and not isinstance(raw_count, bool) and raw_count >= 0
            else len(results)
        )
        return validate_search_response(
            {
                "returnedCount": len(results),
                "totalMatched": total,
                "resultsTruncated": total > len(results),
                "results": results,
            },
            budget=budget,
        )

    async def get(
        self,
        *,
        evidence_id: str,
        cursor: str | None,
        max_content_chars: int,
    ) -> dict[str, Any]:
        if cursor is not None:
            raise ProviderProtocolViolation("legacy get does not support cursors")
        identity = self._evidence.get(evidence_id)
        if identity is None:
            raise ProviderNotFound("legacy evidence is not available in this process")
        chunk_id, document_id = identity
        try:
            raw = await asyncio.to_thread(
                self._backend.get,
                chunk_id=chunk_id,
                document_id=None if chunk_id else document_id,
            )
        except Exception as error:
            raise ProviderUnavailable("legacy knowledge backend is unavailable") from error
        if not isinstance(raw, dict):
            raise ProviderNotFound("legacy evidence was not found")
        title = _optional_text(raw.get("title")) or document_id or chunk_id or "Evidence"
        source = _optional_text(raw.get("source")) or ""
        locator = _optional_text(raw.get("citation") or raw.get("sourcePath"))
        content = _optional_text(raw.get("text") or raw.get("content")) or ""
        citation: dict[str, str] = {"title": title}
        if source:
            citation["source"] = source
        if locator:
            citation["locator"] = locator
        return {
            "evidenceId": evidence_id,
            "document": {"title": title, "source": source},
            "content": content[:max_content_chars],
            "previousCursor": None,
            "nextCursor": None,
            "citation": citation,
            "legacyLimitedGet": True,
        }

    async def close(self) -> None:
        close = getattr(self._backend, "close", None)
        if callable(close):
            result = close()
            if hasattr(result, "__await__"):
                await result


def _legacy_evidence_id(chunk_id: str | None, document_id: str | None) -> str:
    value = f"{chunk_id or ''}\0{document_id or ''}".encode()
    return f"legacy_ev_{hashlib.sha256(value).hexdigest()[:24]}"


def _optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None
