"""Memory source search helpers used by adapter surfaces."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from opensquilla.memory.types import MemorySearchOpts, SearchIntent

MEMORY_SOURCE_SEARCH_DEFAULT_RESULTS: Final[int] = 10
MEMORY_SOURCE_SEARCH_MAX_RESULTS: Final[int] = 20


@dataclass(frozen=True, slots=True)
class MemorySourceSearchRow:
    chunk_id: str
    path: str
    source: str
    start_line: int
    end_line: int
    snippet: str
    score: float
    vector_score: float | None
    text_score: float | None
    chunk_hash: str | None
    citation: str | None


async def search_memory_sources(
    searcher: Any,
    query: str,
    *,
    max_results: int = MEMORY_SOURCE_SEARCH_DEFAULT_RESULTS,
    min_score: float = 0.0,
) -> list[MemorySourceSearchRow]:
    opts = MemorySearchOpts(max_results=max_results, min_score=min_score)
    results = await searcher.search(query, opts, intent=SearchIntent.ADMIN)
    return [memory_source_search_row(result) for result in results]


def memory_source_search_row(result: Any) -> MemorySourceSearchRow:
    source = getattr(result, "source", "")
    source_value = getattr(source, "value", source)
    return MemorySourceSearchRow(
        chunk_id=getattr(result, "chunk_id", ""),
        path=getattr(result, "path", ""),
        source=str(source_value),
        start_line=getattr(result, "start_line", 0),
        end_line=getattr(result, "end_line", 0),
        snippet=getattr(result, "snippet", ""),
        score=getattr(result, "score", 0.0),
        vector_score=getattr(result, "vector_score", None),
        text_score=getattr(result, "text_score", None),
        chunk_hash=getattr(result, "chunk_hash", None),
        citation=getattr(result, "citation", None),
    )
