from __future__ import annotations

from types import SimpleNamespace

import pytest

from opensquilla.memory.source_search import memory_source_search_row, search_memory_sources
from opensquilla.memory.types import (
    MemorySearchOpts,
    MemorySearchResult,
    MemorySource,
    SearchIntent,
)


class FakeMemorySearcher:
    def __init__(self, results: list[MemorySearchResult]) -> None:
        self.results = results
        self.calls: list[tuple[str, MemorySearchOpts, SearchIntent]] = []

    async def search(
        self,
        query: str,
        opts: MemorySearchOpts,
        *,
        intent: SearchIntent,
    ) -> list[MemorySearchResult]:
        self.calls.append((query, opts, intent))
        return self.results


def _result() -> MemorySearchResult:
    return MemorySearchResult(
        chunk_id="chunk-1",
        path="memory/a.md",
        source=MemorySource.memory,
        start_line=1,
        end_line=2,
        snippet="alpha snippet",
        score=0.9,
        vector_score=0.8,
        text_score=0.7,
        chunk_hash="hash-1",
        citation="memory/a.md#L1-L2",
    )


@pytest.mark.asyncio
async def test_search_memory_sources_uses_admin_intent_and_returns_rows() -> None:
    searcher = FakeMemorySearcher([_result()])

    rows = await search_memory_sources(searcher, "alpha", max_results=3, min_score=0.25)

    assert searcher.calls[0][0] == "alpha"
    assert searcher.calls[0][1].max_results == 3
    assert searcher.calls[0][1].min_score == 0.25
    assert searcher.calls[0][2] is SearchIntent.ADMIN
    assert rows[0].chunk_id == "chunk-1"
    assert rows[0].source == "memory"
    assert rows[0].text_score == 0.7
    assert rows[0].citation == "memory/a.md#L1-L2"


def test_memory_source_search_row_normalizes_missing_attributes() -> None:
    row = memory_source_search_row(SimpleNamespace(source="legacy"))

    assert row.chunk_id == ""
    assert row.path == ""
    assert row.source == "legacy"
    assert row.start_line == 0
    assert row.end_line == 0
    assert row.snippet == ""
    assert row.score == 0.0
    assert row.vector_score is None
    assert row.text_score is None
    assert row.chunk_hash is None
    assert row.citation is None
