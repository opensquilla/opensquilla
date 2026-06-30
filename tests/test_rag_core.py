from __future__ import annotations

from types import SimpleNamespace

import pytest

from opensquilla.gateway.config import GatewayConfig, RagConfig, RagSourceConfig
from opensquilla.rag.chunking import chunk_document
from opensquilla.rag.errors import RagValidationError
from opensquilla.rag.ingestion import IngestionService
from opensquilla.rag.manager import RagManager
from opensquilla.rag.parsers import MarkdownParser
from opensquilla.rag.paths import normalize_relative_path, normalize_source_root, rag_db_path
from opensquilla.rag.retrieval import RetrievalService
from opensquilla.rag.scanner import ScanCandidate, ScanSkip, scan_source
from opensquilla.rag.sources import SourceRegistry
from opensquilla.rag.store import RagStore
from opensquilla.rag.types import RagRetrievalMode, RagSearchRequest


class FakeEmbeddingProvider:
    provider_id = "fake"
    model = "fake-3d"

    async def probe(self):
        return True, None

    async def embed_query(self, text: str) -> list[float]:
        return [1.0, 0.0, 0.0] if "alpha" in text else [0.0, 1.0, 0.0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [await self.embed_query(text) for text in texts]


def test_rag_config_defaults_are_conservative():
    config = RagConfig()

    assert config.enabled is False
    assert config.retrieval_mode == "hybrid"
    assert config.embedding.provider == "auto"


def test_rag_config_rejects_unsafe_values():
    with pytest.raises(ValueError):
        RagConfig(db_name="../rag.db")
    with pytest.raises(ValueError):
        RagConfig(chunk_size=300, chunk_overlap=300)
    with pytest.raises(ValueError):
        RagSourceConfig(path="/tmp/docs", source_id="bad/source")


def test_rag_paths_stay_inside_state_and_source(tmp_path):
    config = GatewayConfig(state_dir=str(tmp_path / "state"))

    assert rag_db_path(config) == tmp_path / "state" / "rag" / "rag.db"
    with pytest.raises(RagValidationError):
        normalize_source_root("/")
    with pytest.raises(RagValidationError):
        normalize_relative_path("../secret")


@pytest.mark.asyncio
async def test_parser_and_chunking_preserve_title_and_lines(tmp_path):
    doc = tmp_path / "guide.md"
    doc.write_text("# Setup\n\nThe keyword is cerulean.\n\n## Install\nRun it.\n", encoding="utf-8")

    parsed = await MarkdownParser().parse(doc, relative_path="guide.md")
    chunks = chunk_document(parsed, chunk_size=30, chunk_overlap=5)

    assert parsed.title == "Setup"
    assert chunks
    assert chunks[0].line_start == 1
    assert any(chunk.section in {"Setup", "Install"} for chunk in chunks)


def test_scanner_applies_excludes_and_limits(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.md").write_text("alpha", encoding="utf-8")
    (docs / ".env").write_text("secret", encoding="utf-8")
    (docs / "skip.log").write_text("log", encoding="utf-8")
    source = SimpleNamespace(
        root_path=str(docs),
        include=(),
        exclude=(),
    )

    results = scan_source(source, config=RagConfig(enabled=True))

    candidates = [item for item in results if isinstance(item, ScanCandidate)]
    skips = [item for item in results if isinstance(item, ScanSkip)]
    assert [candidate.relative_path for candidate in candidates] == ["a.md"]
    assert {skip.reason for skip in skips} >= {"excluded"}


@pytest.mark.asyncio
async def test_store_source_ingestion_and_fts_search(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "guide.md").write_text("# Guide\n\nThe launch keyword is cerulean.\n", encoding="utf-8")
    config = RagConfig(enabled=True, retrieval_mode="fts")
    store = RagStore(tmp_path / "rag.db")
    await store.initialize()
    try:
        registry = SourceRegistry(store)
        source, created = await registry.add_source(path=str(docs), collection_id="default")
        ingestion = IngestionService(store=store, config=config)
        retrieval = RetrievalService(store=store, config=config)

        job = await ingestion.sync_source(source.source_id)
        payload = await retrieval.search(
            RagSearchRequest(query="cerulean", mode=RagRetrievalMode.FTS, limit=5)
        )

        assert created is True
        assert job.status.value == "succeeded"
        assert payload["results"][0].document_path == "guide.md"
        assert payload["results"][0].source_kind == "rag"
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_source_missing_does_not_clear_historical_index(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "guide.md").write_text("The keyword is durable.", encoding="utf-8")
    config = RagConfig(enabled=True, retrieval_mode="fts")
    store = RagStore(tmp_path / "rag.db")
    await store.initialize()
    try:
        registry = SourceRegistry(store)
        source, _created = await registry.add_source(path=str(docs), collection_id="default")
        ingestion = IngestionService(store=store, config=config)
        retrieval = RetrievalService(store=store, config=config)
        await ingestion.sync_source(source.source_id)
        (docs / "guide.md").unlink()
        docs.rmdir()

        job = await ingestion.sync_source(source.source_id)
        payload = await retrieval.search(
            RagSearchRequest(query="durable", mode=RagRetrievalMode.FTS, limit=5)
        )

        assert job.status.value == "failed"
        assert payload["results"][0].document_path == "guide.md"
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_hybrid_falls_back_to_fts_when_vector_unavailable(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "guide.md").write_text("The keyword is fallback.", encoding="utf-8")
    config = RagConfig(enabled=True, retrieval_mode="hybrid")
    store = RagStore(tmp_path / "rag.db")
    await store.initialize()
    try:
        registry = SourceRegistry(store)
        source, _created = await registry.add_source(path=str(docs), collection_id="default")
        await IngestionService(store=store, config=config).sync_source(source.source_id)
        retrieval = RetrievalService(store=store, config=config, embedding_provider=None)

        payload = await retrieval.search(RagSearchRequest(query="fallback", limit=5))

        assert payload["effectiveMode"] == "fts"
        assert payload["fallback"]["reason"] == "embedding_unavailable"
        assert payload["results"][0].document_path == "guide.md"
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_hybrid_search_reports_explainable_weights_and_candidates(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.md").write_text("alpha vector target", encoding="utf-8")
    (docs / "b.md").write_text("alpha beta related", encoding="utf-8")
    config = RagConfig(
        enabled=True,
        retrieval_mode="hybrid",
        chunk_size=200,
        chunk_overlap=20,
        text_weight=0.25,
        vector_weight=0.75,
    )
    provider = FakeEmbeddingProvider()
    store = RagStore(tmp_path / "rag.db")
    await store.initialize(vector_dimensions=3)
    try:
        registry = SourceRegistry(store)
        source, _created = await registry.add_source(path=str(docs), collection_id="default")
        ingestion = IngestionService(
            store=store,
            config=config,
            embedding_provider=provider,
            embedding_fingerprint="fake",
        )
        await ingestion.sync_source(source.source_id)
        retrieval = RetrievalService(store=store, config=config, embedding_provider=provider)

        payload = await retrieval.search(RagSearchRequest(query="alpha", limit=5))

        assert payload["effectiveMode"] == "hybrid"
        scoring = payload["diagnostics"]["scoring"]
        assert scoring["strategy"] == "weighted_sum"
        assert scoring["textWeight"] == 0.25
        assert scoring["vectorWeight"] == 0.75
        assert scoring["formula"] == "score = textWeight * textScore + vectorWeight * vectorScore"
        assert payload["diagnostics"]["candidates"]["fts"] >= 1
        assert payload["diagnostics"]["candidates"]["vector"] >= 1
        assert payload["diagnostics"]["candidates"]["merged"] >= 1
        result = payload["results"][0]
        assert result.metadata["scoreBreakdown"]["textWeight"] == 0.25
        assert result.metadata["scoreBreakdown"]["vectorWeight"] == 0.75
        assert result.metadata["scoreBreakdown"]["formula"] == scoring["formula"]
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_vector_only_uses_sqlite_vec_when_available(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.md").write_text("alpha vector target", encoding="utf-8")
    (docs / "b.md").write_text("beta unrelated", encoding="utf-8")
    config = RagConfig(enabled=True, retrieval_mode="hybrid", chunk_size=200, chunk_overlap=20)
    provider = FakeEmbeddingProvider()
    store = RagStore(tmp_path / "rag.db")
    await store.initialize(vector_dimensions=3)
    try:
        registry = SourceRegistry(store)
        source, _created = await registry.add_source(path=str(docs), collection_id="default")
        ingestion = IngestionService(
            store=store,
            config=config,
            embedding_provider=provider,
            embedding_fingerprint="fake",
        )
        await ingestion.sync_source(source.source_id)
        retrieval = RetrievalService(store=store, config=config, embedding_provider=provider)

        payload = await retrieval.search(
            RagSearchRequest(query="alpha", mode=RagRetrievalMode.VECTOR_ONLY, limit=2)
        )

        assert store.vec_available is True
        assert payload["effectiveMode"] == "vector_only"
        assert payload["results"][0].document_path == "a.md"
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_vector_index_is_available_after_store_reopen(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.md").write_text("alpha vector target", encoding="utf-8")
    (docs / "b.md").write_text("beta unrelated", encoding="utf-8")
    config = RagConfig(enabled=True, retrieval_mode="hybrid", chunk_size=200, chunk_overlap=20)
    provider = FakeEmbeddingProvider()
    db_path = tmp_path / "rag.db"
    store = RagStore(db_path)
    await store.initialize(vector_dimensions=3)
    try:
        registry = SourceRegistry(store)
        source, _created = await registry.add_source(path=str(docs), collection_id="default")
        ingestion = IngestionService(
            store=store,
            config=config,
            embedding_provider=provider,
            embedding_fingerprint="fake",
        )
        await ingestion.sync_source(source.source_id)

        assert store.vec_available is True
    finally:
        await store.close()

    restarted_store = RagStore(db_path)
    await restarted_store.initialize()
    try:
        retrieval = RetrievalService(
            store=restarted_store,
            config=config,
            embedding_provider=provider,
        )

        payload = await retrieval.search(
            RagSearchRequest(query="alpha", mode=RagRetrievalMode.VECTOR_ONLY, limit=2)
        )

        assert restarted_store.vec_available is True
        assert restarted_store.vec_dimensions == 3
        assert payload["effectiveMode"] == "vector_only"
        assert payload["results"][0].document_path == "a.md"
    finally:
        await restarted_store.close()


@pytest.mark.asyncio
async def test_manager_add_sync_search_and_show(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "guide.md").write_text("# Guide\n\nThe keyword is manager.", encoding="utf-8")
    gateway_config = GatewayConfig(
        state_dir=str(tmp_path / "state"),
        rag=RagConfig(enabled=True, retrieval_mode="fts"),
    )
    store = RagStore(tmp_path / "rag.db")
    await store.initialize()
    try:
        registry = SourceRegistry(store)
        ingestion = IngestionService(store=store, config=gateway_config.rag)
        retrieval = RetrievalService(store=store, config=gateway_config.rag)
        manager = RagManager(
            config=gateway_config,
            store=store,
            source_registry=registry,
            ingestion=ingestion,
            retrieval=retrieval,
            embedding_decision=SimpleNamespace(
                enabled=False,
                effective_provider="none",
                requested_provider="auto",
                model="fts-only",
                dimensions=None,
                fingerprint="none",
                reason="test",
            ),
        )

        added = await manager.add_source(path=str(docs), index=True)
        search = await manager.search(RagSearchRequest(query="manager", mode=RagRetrievalMode.FTS))
        shown = await manager.show(chunk_id=search["results"][0]["chunkId"])

        assert added["source"]["status"] == "stale"
        assert search["results"][0]["citation"]["label"] == "[来源：guide.md]"
        assert shown["citation"]["label"] == "[来源：guide.md]"
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_manager_status_reports_ingestion_health_and_latest_job(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "guide.md").write_text("# Guide\n\nThe keyword is status.", encoding="utf-8")
    gateway_config = GatewayConfig(
        state_dir=str(tmp_path / "state"),
        rag=RagConfig(enabled=True, retrieval_mode="fts"),
    )
    store = RagStore(tmp_path / "rag.db")
    await store.initialize()
    try:
        registry = SourceRegistry(store)
        ingestion = IngestionService(store=store, config=gateway_config.rag)
        retrieval = RetrievalService(store=store, config=gateway_config.rag)
        manager = RagManager(
            config=gateway_config,
            store=store,
            source_registry=registry,
            ingestion=ingestion,
            retrieval=retrieval,
            embedding_decision=SimpleNamespace(
                enabled=False,
                effective_provider="none",
                requested_provider="auto",
                model="fts-only",
                dimensions=None,
                fingerprint="none",
                reason="test",
            ),
        )

        await manager.add_source(path=str(docs), index=True)
        status = await manager.status()

        ingestion_status = status["ingestion"]
        assert ingestion_status["activeJobs"] == 0
        assert ingestion_status["latestJob"]["status"] == "succeeded"
        assert ingestion_status["latestJob"]["filesSeen"] == 1
        assert ingestion_status["latestJob"]["chunksWritten"] >= 1
        assert ingestion_status["latestJob"]["durationMs"] is not None
        assert ingestion_status["summary"]["succeeded"] >= 1
        assert status["counts"]["chunks"] >= 1
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_manager_can_disable_enable_and_remove_source(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "guide.md").write_text("# Guide\n\nThe keyword is lifecycle.", encoding="utf-8")
    gateway_config = GatewayConfig(
        state_dir=str(tmp_path / "state"),
        rag=RagConfig(enabled=True, retrieval_mode="fts"),
    )
    store = RagStore(tmp_path / "rag.db")
    await store.initialize()
    try:
        registry = SourceRegistry(store)
        ingestion = IngestionService(store=store, config=gateway_config.rag)
        retrieval = RetrievalService(store=store, config=gateway_config.rag)
        manager = RagManager(
            config=gateway_config,
            store=store,
            source_registry=registry,
            ingestion=ingestion,
            retrieval=retrieval,
            embedding_decision=SimpleNamespace(
                enabled=False,
                effective_provider="none",
                requested_provider="auto",
                model="fts-only",
                dimensions=None,
                fingerprint="none",
                reason="test",
            ),
        )

        added = await manager.add_source(path=str(docs), index=True)
        source_id = added["source"]["sourceId"]

        disabled = await manager.disable_source(source_id)
        disabled_search = await manager.search(
            RagSearchRequest(query="lifecycle", mode=RagRetrievalMode.FTS)
        )
        enabled = await manager.enable_source(source_id)
        enabled_search = await manager.search(
            RagSearchRequest(query="lifecycle", mode=RagRetrievalMode.FTS)
        )
        removed = await manager.remove_source(source_id)
        removed_search = await manager.search(
            RagSearchRequest(query="lifecycle", mode=RagRetrievalMode.FTS)
        )

        assert disabled["enabled"] is False
        assert disabled["status"] == "disabled"
        assert disabled_search["results"] == []
        assert enabled["enabled"] is True
        assert enabled["status"] in {"stale", "missing"}
        assert enabled_search["results"][0]["path"] == "guide.md"
        assert removed["removed"] is True
        assert removed["sourceId"] == source_id
        assert removed_search["results"] == []
        assert await store.get_source(source_id) is None
    finally:
        await store.close()
