from __future__ import annotations

from dataclasses import dataclass

import pytest

from opensquilla.rag_provider.legacy import LEGACY_WARNING, LegacyKnowledgeAdapter
from opensquilla.rag_provider.protocol import ProviderNotFound, SearchBudget
from opensquilla.rag_provider.runtime import RagProviderRuntime, RagProviderState
from opensquilla.tools.registry import ToolRegistry


class Backend:
    def __init__(self) -> None:
        self.search_calls = 0

    def search(self, query: str, *, top_k: int, filters: dict | None):
        self.search_calls += 1
        return {
            "count": 1,
            "results": [
                {
                    "chunkId": "chunk-a",
                    "documentId": "doc-a",
                    "title": "Legacy document",
                    "source": "legacy-source",
                    "citation": "legacy/path.md#page=1",
                    "snippet": "matching legacy evidence",
                    "score": 99.0,
                    "vectorScore": 0.9,
                }
            ],
        }

    def get(self, *, chunk_id: str | None, document_id: str | None):
        if chunk_id != "chunk-a":
            return None
        return {
            "chunkId": "chunk-a",
            "documentId": "doc-a",
            "title": "Legacy document",
            "source": "legacy-source",
            "citation": "legacy/path.md#page=1",
            "text": "legacy chunk text, not guaranteed full document text",
        }


@dataclass
class Config:
    enabled: bool = True
    legacy_knowledge_adapter: bool = True
    probe_interval_seconds: float = 60
    unavailable_after_seconds: float = 300
    max_consecutive_failures: int = 3
    retrieval_profile_override: str | None = None
    collection_scope: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.collection_scope is None:
            self.collection_scope = []


@pytest.mark.asyncio
async def test_legacy_search_maps_to_minimal_standard_evidence() -> None:
    adapter = LegacyKnowledgeAdapter(Backend())

    first = await adapter.search(
        query="NAND",
        limit=8,
        budget=SearchBudget(max_snippet_chars=800, max_total_chars=12_000),
    )
    second = await adapter.search(
        query="NAND",
        limit=8,
        budget=SearchBudget(max_snippet_chars=800, max_total_chars=12_000),
    )

    assert first.payload == second.payload
    item = first.payload["results"][0]
    assert set(item) == {"evidenceId", "snippet", "snippetTruncated", "citation"}
    assert "score" not in item


@pytest.mark.asyncio
async def test_legacy_get_is_explicitly_limited_and_does_not_invent_cursors() -> None:
    adapter = LegacyKnowledgeAdapter(Backend())
    search = await adapter.search(
        query="NAND",
        limit=8,
        budget=SearchBudget(max_snippet_chars=800, max_total_chars=12_000),
    )
    evidence_id = search.payload["results"][0]["evidenceId"]

    payload = await adapter.get(
        evidence_id=evidence_id,
        cursor=None,
        max_content_chars=8_000,
    )

    assert payload["previousCursor"] is None
    assert payload["nextCursor"] is None
    assert payload["legacyLimitedGet"] is True
    with pytest.raises(ProviderNotFound):
        await adapter.get(evidence_id="unknown", cursor=None, max_content_chars=8_000)


@pytest.mark.asyncio
async def test_runtime_reports_legacy_and_fixed_warning() -> None:
    adapter = LegacyKnowledgeAdapter(Backend())
    registry = ToolRegistry()
    runtime = RagProviderRuntime(Config(), adapter, registry)

    await runtime.start(start_probe_loop=False)

    assert runtime.snapshot().state is RagProviderState.LEGACY
    assert runtime.snapshot().to_wire()["warning"] == LEGACY_WARNING
    assert {"knowledge_search", "knowledge_get"}.issubset(registry.list_names())
