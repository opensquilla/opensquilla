from __future__ import annotations

import pytest

from opensquilla.compat import aiosqlite
from opensquilla.memory.embedding import NullEmbeddingProvider
from opensquilla.memory.retrieval import MemoryRetriever
from opensquilla.memory.store import LongTermMemoryStore
from opensquilla.memory.types import (
    LEXICAL_GUARANTEE_METADATA_KEY,
    LEXICAL_GUARANTEE_METADATA_VALUE,
    RELAXED_KEYWORD_MATCH_METADATA_KEY,
    RELAXED_KEYWORD_MATCH_METADATA_VALUE,
    MemorySearchOpts,
    MemorySearchResult,
    MemorySource,
    SearchMode,
)


def _assert_relaxed_keyword_match(result: MemorySearchResult) -> None:
    assert (
        result.metadata[RELAXED_KEYWORD_MATCH_METADATA_KEY]
        == RELAXED_KEYWORD_MATCH_METADATA_VALUE
    )


def _assert_lexical_guarantee(result: MemorySearchResult) -> None:
    assert (
        result.metadata[LEXICAL_GUARANTEE_METADATA_KEY]
        == LEXICAL_GUARANTEE_METADATA_VALUE
    )


class _RecordingVectorCursor:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc_info):
        return None

    async def fetchall(self):
        return [("wanted", 0.0)]


class _RecordingVectorDb:
    def __init__(self) -> None:
        self.sql = ""
        self.params = ()

    def execute(self, sql, params):
        self.sql = sql
        self.params = params
        return _RecordingVectorCursor()


@pytest.mark.asyncio
async def test_fts_search_tags_relaxed_keyword_hits_when_default_threshold_drops_all():
    store = LongTermMemoryStore(
        ":memory:",
        embedding_provider=NullEmbeddingProvider(),
    )
    store._db = await aiosqlite.connect(":memory:")  # type: ignore[assignment]
    try:
        await store._ensure_schema()
        await store.index_file("MEMORY.md", "alpha keyword only")

        results = await store._fts_search("alpha", k=3, min_score=0.35)

        assert results
        assert results[0].path == "MEMORY.md"
        _assert_relaxed_keyword_match(results[0])
    finally:
        await store._db.close()  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_vector_search_filters_by_embedding_model():
    store = LongTermMemoryStore(
        ":memory:",
        embedding_provider=NullEmbeddingProvider(),
    )
    db = _RecordingVectorDb()
    store._db = db  # type: ignore[assignment]

    results = await store._vector_search([0.0], 3, "model-a")

    assert results == [("wanted", 1.0)]
    assert "JOIN chunks c ON c.id = v.id" in db.sql
    assert "AND c.model = ?" in db.sql
    assert db.params[1:] == (3, "model-a")


@pytest.mark.asyncio
async def test_hybrid_search_keeps_keyword_hit_when_strict_threshold_drops_all(monkeypatch):
    store = LongTermMemoryStore(
        ":memory:",
        embedding_provider=NullEmbeddingProvider(),
    )
    store._db = await aiosqlite.connect(":memory:")  # type: ignore[assignment]
    try:
        await store._ensure_schema()
        await store._db.execute(  # type: ignore[union-attr]
            """INSERT INTO chunks
               (id, path, source, start_line, end_line, hash, model, text, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "kw-only",
                "MEMORY.md",
                MemorySource.memory.value,
                1,
                1,
                "hash",
                "fts-only",
                "alpha keyword only",
                0.0,
            ),
        )
        await store._db.commit()  # type: ignore[union-attr]

        async def no_vector_results(_query_vec, _k, _model, **_kwargs):
            return []

        async def keyword_results(_query, _k, _min_score, **_kwargs):
            return [
                MemorySearchResult(
                    chunk_id="kw-only",
                    path="MEMORY.md",
                    source=MemorySource.memory,
                    start_line=1,
                    end_line=1,
                    snippet="alpha keyword only",
                    score=1.0,
                    text_score=1.0,
                    text="alpha keyword only",
                )
            ]

        monkeypatch.setattr(store, "_vector_search", no_vector_results)
        monkeypatch.setattr(store, "_fts_search", keyword_results)

        results = await store._hybrid_search(
            "alpha",
            [0.0],
            k=3,
            min_score=0.35,
            vector_weight=0.7,
            text_weight=0.3,
        )

        assert [result.chunk_id for result in results] == ["kw-only"]
        assert results[0].score == pytest.approx(0.3)
        assert results[0].text_score == pytest.approx(1.0)
        _assert_relaxed_keyword_match(results[0])
    finally:
        await store._db.close()  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_hybrid_search_keeps_high_text_hit_when_vector_score_is_zero(monkeypatch):
    store = LongTermMemoryStore(
        ":memory:",
        embedding_provider=NullEmbeddingProvider(),
    )
    store._db = await aiosqlite.connect(":memory:")  # type: ignore[assignment]
    try:
        await store._ensure_schema()
        await store._db.execute(  # type: ignore[union-attr]
            """INSERT INTO chunks
               (id, path, source, start_line, end_line, hash, model, text, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "high-text-low-vector",
                "memory/synthetic-keyword.md",
                MemorySource.memory.value,
                1,
                1,
                "hash",
                "fts-only",
                "synthetic keyword evidence only",
                0.0,
            ),
        )
        await store._db.commit()  # type: ignore[union-attr]

        async def zero_vector_result(_query_vec, _k, _model, **_kwargs):
            return [("high-text-low-vector", 0.0)]

        async def high_text_result(_query, _k, _min_score, **_kwargs):
            return [
                MemorySearchResult(
                    chunk_id="high-text-low-vector",
                    path="memory/synthetic-keyword.md",
                    source=MemorySource.memory,
                    start_line=1,
                    end_line=1,
                    snippet="synthetic keyword evidence only",
                    score=0.94,
                    text_score=0.94,
                    text="synthetic keyword evidence only",
                )
            ]

        monkeypatch.setattr(store, "_vector_search", zero_vector_result)
        monkeypatch.setattr(store, "_fts_search", high_text_result)

        results = await store._hybrid_search(
            "synthetic keyword",
            [0.0],
            k=3,
            min_score=0.35,
            vector_weight=0.7,
            text_weight=0.3,
        )

        assert [result.chunk_id for result in results] == ["high-text-low-vector"]
        assert results[0].vector_score == pytest.approx(0.0)
        assert results[0].text_score == pytest.approx(0.94)
        _assert_relaxed_keyword_match(results[0])
    finally:
        await store._db.close()  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_hybrid_search_guarantees_strong_keyword_hit_when_vector_hits_exist(monkeypatch):
    store = LongTermMemoryStore(
        ":memory:",
        embedding_provider=NullEmbeddingProvider(),
    )
    store._db = await aiosqlite.connect(":memory:")  # type: ignore[assignment]
    try:
        await store._ensure_schema()
        for chunk_id, text in (
            ("semantic-1", "semantic neighbor one"),
            ("semantic-2", "semantic neighbor two"),
            ("semantic-3", "semantic neighbor three"),
            ("lexical-strong", "alpha keyword exact"),
            ("lexical-weak", "alpha weak"),
        ):
            await store._db.execute(  # type: ignore[union-attr]
                """INSERT INTO chunks
                   (id, path, source, start_line, end_line, hash, model, text, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    chunk_id,
                    f"memory/{chunk_id}.md",
                    MemorySource.memory.value,
                    1,
                    1,
                    f"hash-{chunk_id}",
                    "fts-only",
                    text,
                    0.0,
                ),
            )
        await store._db.commit()  # type: ignore[union-attr]

        async def vector_results(_query_vec, _k, _model, **_kwargs):
            return [
                ("semantic-1", 0.9),
                ("semantic-2", 0.8),
                ("semantic-3", 0.7),
            ]

        async def keyword_results(_query, _k, _min_score, **_kwargs):
            return [
                MemorySearchResult(
                    chunk_id="lexical-strong",
                    path="memory/lexical-strong.md",
                    source=MemorySource.memory,
                    start_line=1,
                    end_line=1,
                    snippet="alpha keyword exact",
                    score=1.0,
                    text_score=1.0,
                    text="alpha keyword exact",
                ),
                MemorySearchResult(
                    chunk_id="lexical-weak",
                    path="memory/lexical-weak.md",
                    source=MemorySource.memory,
                    start_line=1,
                    end_line=1,
                    snippet="alpha weak",
                    score=0.2,
                    text_score=0.2,
                    text="alpha weak",
                ),
            ]

        monkeypatch.setattr(store, "_vector_search", vector_results)
        monkeypatch.setattr(store, "_fts_search", keyword_results)

        results = await store._hybrid_search(
            "alpha",
            [0.0],
            k=3,
            min_score=0.35,
            vector_weight=0.7,
            text_weight=0.3,
        )

        chunk_ids = [result.chunk_id for result in results]
        assert len(results) == 3
        assert "lexical-strong" in chunk_ids
        assert "lexical-weak" not in chunk_ids
        _assert_lexical_guarantee(
            next(result for result in results if result.chunk_id == "lexical-strong")
        )
    finally:
        await store._db.close()  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_retriever_preserves_store_relaxed_keyword_hits():
    class _Store:
        async def search(self, **kwargs):
            assert kwargs["min_score"] == 0.35
            return [
                MemorySearchResult(
                    chunk_id="kw-only",
                    path="MEMORY.md",
                    source=MemorySource.memory,
                    start_line=1,
                    end_line=1,
                    snippet="alpha keyword only",
                    score=0.3,
                    text_score=1.0,
                    text="alpha keyword only",
                    metadata={
                        RELAXED_KEYWORD_MATCH_METADATA_KEY: (
                            RELAXED_KEYWORD_MATCH_METADATA_VALUE
                        )
                    },
                )
            ], SearchMode.hybrid

    retriever = MemoryRetriever(_Store())  # type: ignore[arg-type]
    results = await retriever.search(
        "alpha",
        MemorySearchOpts(max_results=3, min_score=0.35),
    )

    assert [result.chunk_id for result in results] == ["kw-only"]


@pytest.mark.asyncio
async def test_retriever_preserves_store_lexical_guaranteed_hits():
    class _Store:
        async def search(self, **kwargs):
            assert kwargs["min_score"] == 0.35
            return [
                MemorySearchResult(
                    chunk_id="semantic",
                    path="memory/semantic.md",
                    source=MemorySource.memory,
                    start_line=1,
                    end_line=1,
                    snippet="semantic neighbor",
                    score=0.6,
                    vector_score=0.86,
                    text_score=0.0,
                    text="semantic neighbor",
                ),
                MemorySearchResult(
                    chunk_id="lexical",
                    path="MEMORY.md",
                    source=MemorySource.memory,
                    start_line=1,
                    end_line=1,
                    snippet="alpha keyword only",
                    score=0.3,
                    text_score=1.0,
                    text="alpha keyword only",
                    metadata={
                        LEXICAL_GUARANTEE_METADATA_KEY: (
                            LEXICAL_GUARANTEE_METADATA_VALUE
                        )
                    },
                ),
            ], SearchMode.hybrid

    retriever = MemoryRetriever(_Store())  # type: ignore[arg-type]
    results = await retriever.search(
        "alpha",
        MemorySearchOpts(max_results=3, min_score=0.35),
    )

    assert [result.chunk_id for result in results] == ["semantic", "lexical"]
