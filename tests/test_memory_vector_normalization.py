from __future__ import annotations

import json
import math
import struct
from pathlib import Path

import pytest

from opensquilla.memory.store import (
    VECTOR_NORMALIZATION_META_KEY,
    VECTOR_NORMALIZATION_META_VALUE,
    LongTermMemoryStore,
)
from opensquilla.memory.types import MemorySource


class _RawMagnitudeEmbeddingProvider:
    def __init__(
        self,
        *,
        provider_id: str,
        model: str,
        vector: list[float],
    ) -> None:
        self._provider_id = provider_id
        self._model = model
        self._vector = vector
        self._vector_dims = len(vector)

    @property
    def provider_id(self) -> str:
        return self._provider_id

    @property
    def model(self) -> str:
        return self._model

    async def embed_query(self, _text: str) -> list[float]:
        return [value * 2 for value in self._vector]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self._vector for _text in texts]

    async def probe(self) -> tuple[bool, str | None]:
        return True, None


class _RecordingVectorCursor:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc_info):
        return None

    async def fetchall(self):
        return [("wanted", 0.0)]


class _RecordingVectorDb:
    def __init__(self) -> None:
        self.params = ()

    def execute(self, _sql, params):
        self.params = params
        return _RecordingVectorCursor()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider_id", "model", "path", "content", "vector"),
    [
        (
            "local",
            "BAAI/bge-small-zh-v1.5",
            "memory/synthetic-zh.md",
            "合成中文资料：青岚城市的公共机器人展会日程与场馆说明。",
            [9.0, 12.0, 0.0, 0.0],
        ),
        (
            "local",
            "BAAI/bge-small-zh-v1.5",
            "memory/synthetic-en.md",
            "Synthetic English note about Blue Harbor robotics planning.",
            [0.0, 8.0, 15.0, 0.0],
        ),
        (
            "openai",
            "text-embedding-3-small",
            "memory/synthetic-multilingual.md",
            "Synthetic multilingual note: Ciudad Azul, 青い街, ville bleue.",
            [6.0, 0.0, 0.0, 8.0],
        ),
    ],
)
async def test_indexed_embeddings_are_l2_normalized_at_store_boundary(
    tmp_path: Path,
    provider_id: str,
    model: str,
    path: str,
    content: str,
    vector: list[float],
) -> None:
    store = LongTermMemoryStore(
        str(tmp_path / "memory.db"),
        embedding_provider=_RawMagnitudeEmbeddingProvider(
            provider_id=provider_id,
            model=model,
            vector=vector,
        ),
    )
    await store.initialize()
    try:
        await store.index_file(path, content)

        assert store._db is not None
        async with store._db.execute("SELECT embedding FROM chunks") as cur:
            rows = await cur.fetchall()
        assert len(rows) == 1
        stored = json.loads(rows[0][0])
        assert math.sqrt(sum(value * value for value in stored)) == pytest.approx(1.0)
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_vector_query_is_l2_normalized_before_sqlite_vec_match() -> None:
    store = LongTermMemoryStore(
        ":memory:",
        embedding_provider=_RawMagnitudeEmbeddingProvider(
            provider_id="openai",
            model="text-embedding-3-small",
            vector=[3.0, 4.0, 0.0, 0.0],
        ),
    )
    db = _RecordingVectorDb()
    store._db = db  # type: ignore[assignment]

    results = await store._vector_search([30.0, 40.0, 0.0, 0.0], 3, store._provider.model)

    assert results == [("wanted", 1.0)]
    unpacked = struct.unpack("4f", db.params[0])
    assert unpacked == pytest.approx((0.6, 0.8, 0.0, 0.0))


@pytest.mark.asyncio
async def test_normalization_meta_still_rebuilds_missing_vec_table(tmp_path: Path) -> None:
    store = LongTermMemoryStore(
        str(tmp_path / "memory.db"),
        embedding_provider=_RawMagnitudeEmbeddingProvider(
            provider_id="local",
            model="BAAI/bge-small-zh-v1.5",
            vector=[3.0, 4.0, 0.0, 0.0],
        ),
    )
    await store.initialize()
    if not store.vec_available:
        await store.close()
        pytest.skip("sqlite-vec is not available in this environment")

    try:
        assert store._db is not None
        await store._db.execute(
            """INSERT INTO chunks
               (id, path, source, start_line, end_line, hash, model, text, embedding, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "normalized-without-vec-row",
                "memory/synthetic-rebuild.md",
                MemorySource.memory.value,
                1,
                1,
                "hash",
                store._provider.model,
                "Synthetic vec rebuild note.",
                json.dumps([0.6, 0.8, 0.0, 0.0]),
                0.0,
            ),
        )
        await store._db.execute("DROP TABLE IF EXISTS chunks_vec")
        await store._db.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
            (VECTOR_NORMALIZATION_META_KEY, VECTOR_NORMALIZATION_META_VALUE),
        )
        await store._db.commit()

        await store._ensure_vector_normalization()

        async with store._db.execute("SELECT COUNT(*) FROM chunks_vec") as cur:
            row = await cur.fetchone()
        assert row[0] == 1
    finally:
        await store.close()
