"""Legacy memory.db upgrade: schema_version back-fill at connect time.

Per-agent ``memory.db`` files never see yoyo migrations (``apply_pending``
only runs against the session DB), so a database created before the
``schema_version`` column existed keeps its legacy shape forever. Every
``embedding_cache`` INSERT then fails with "no column named schema_version"
— caught, logged, and silently swallowed, so the cache never works again.
``LongTermMemoryStore`` must therefore add the column in place when it
opens such a database. Synthetic fixture data only.
"""

from __future__ import annotations

from pathlib import Path

from opensquilla.compat import aiosqlite
from opensquilla.memory.store import SCHEMA_VERSION, LongTermMemoryStore

# Pre-schema_version shape of the four memory tables: the current store DDL
# minus the schema_version column (the shape V004 was written to back-fill).
_LEGACY_MEMORY_SCHEMA = """
CREATE TABLE files (
    path TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    hash TEXT NOT NULL,
    mtime REAL NOT NULL,
    size INTEGER NOT NULL
);
CREATE TABLE chunks (
    id TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    source TEXT NOT NULL,
    start_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    hash TEXT NOT NULL,
    model TEXT NOT NULL,
    text TEXT NOT NULL,
    embedding TEXT,
    updated_at REAL NOT NULL
);
CREATE TABLE embedding_cache (
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    provider_key TEXT NOT NULL,
    hash TEXT NOT NULL,
    embedding TEXT NOT NULL,
    dims INTEGER NOT NULL,
    updated_at REAL NOT NULL,
    UNIQUE(provider, model, provider_key, hash)
);
CREATE TABLE meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

_TABLES = ("files", "chunks", "embedding_cache", "meta")


async def _create_legacy_db(db_path: Path) -> None:
    db = await aiosqlite.connect(db_path)
    try:
        await db.executescript(_LEGACY_MEMORY_SCHEMA)
        # Stored index version matches the current one, so _ensure_schema's
        # mismatch drop-and-rebuild path must NOT rescue the legacy tables —
        # exactly the case where the in-place column add is required.
        await db.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?)",
            ("memory_index_meta_v1", SCHEMA_VERSION),
        )
        await db.commit()
    finally:
        await db.close()


async def _columns(db: aiosqlite.Connection, table: str) -> set[str]:
    async with db.execute(f"PRAGMA table_info({table})") as cur:
        return {row[1] for row in await cur.fetchall()}


async def test_legacy_memory_db_gains_schema_version_and_cache_writes(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.db"
    await _create_legacy_db(db_path)

    store = LongTermMemoryStore(db_path=db_path)
    await store.initialize()
    try:
        db = store._db
        assert db is not None
        for table in _TABLES:
            assert "schema_version" in await _columns(db, table), (
                f"{table}: schema_version column missing after connect on a legacy DB"
            )

        # The write that used to raise "no column named schema_version" —
        # asserted by row landing, not just by the call not raising, because
        # _store_embedding_cache swallows failures by design.
        await store._store_embedding_cache([("a" * 64, [0.1, 0.2, 0.3])])
        async with db.execute(
            "SELECT dims, schema_version FROM embedding_cache WHERE hash = ?",
            ("a" * 64,),
        ) as cur:
            row = await cur.fetchone()
        assert row is not None, "embedding_cache write did not land on the migrated legacy DB"
        assert row[0] == 3
        assert row[1] == 1
    finally:
        await store.close()


async def test_fresh_memory_db_is_untouched_by_the_backfill(tmp_path: Path) -> None:
    store = LongTermMemoryStore(db_path=tmp_path / "memory.db")
    await store.initialize()
    try:
        db = store._db
        assert db is not None
        for table in _TABLES:
            assert "schema_version" in await _columns(db, table)
    finally:
        await store.close()
