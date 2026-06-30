from __future__ import annotations

import io
import zipfile
from types import SimpleNamespace

import pytest

from opensquilla.gateway.config import GatewayConfig, RagConfig
from opensquilla.rag.errors import RagValidationError
from opensquilla.rag.imports import import_zip_bytes
from opensquilla.rag.ingestion import IngestionService
from opensquilla.rag.manager import RagManager
from opensquilla.rag.retrieval import RetrievalService
from opensquilla.rag.sources import SourceRegistry
from opensquilla.rag.store import RagStore
from opensquilla.rag.types import RagRetrievalMode, RagSearchRequest


def _zip_bytes(files: dict[str, bytes | str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            payload = content.encode("utf-8") if isinstance(content, str) else content
            archive.writestr(name, payload)
    return buffer.getvalue()


def test_import_zip_bytes_extracts_supported_files_and_skips_unsupported(tmp_path):
    target = tmp_path / "files"
    payload = _zip_bytes(
        {
            "docs/guide.md": "# Guide\n\nalpha",
            "notes/readme.txt": "beta",
            "image.png": b"\x89PNG\r\n\x1a\n",
            "__MACOSX/._guide.md": "metadata",
        }
    )

    summary = import_zip_bytes(
        archive_name="docs.zip",
        payload=payload,
        target_dir=target,
        config=RagConfig(enabled=True),
    )

    assert summary["filesImported"] == 2
    assert summary["filesSkipped"] == 2
    assert (target / "docs/guide.md").read_text(encoding="utf-8") == "# Guide\n\nalpha"
    assert (target / "notes/readme.txt").read_text(encoding="utf-8") == "beta"
    assert not (target / "image.png").exists()


@pytest.mark.parametrize(
    "name",
    [
        "../evil.md",
        "/evil.md",
        "C:\\evil.md",
        "docs/../evil.md",
    ],
)
def test_import_zip_bytes_rejects_dangerous_paths(tmp_path, name):
    payload = _zip_bytes({name: "evil"})

    with pytest.raises(RagValidationError):
        import_zip_bytes(
            archive_name="evil.zip",
            payload=payload,
            target_dir=tmp_path / "files",
            config=RagConfig(enabled=True),
        )


def test_import_zip_bytes_rejects_archives_without_supported_files(tmp_path):
    payload = _zip_bytes({"image.png": b"png"})

    with pytest.raises(RagValidationError, match="no supported"):
        import_zip_bytes(
            archive_name="empty.zip",
            payload=payload,
            target_dir=tmp_path / "files",
            config=RagConfig(enabled=True),
        )


def test_import_zip_bytes_rejects_duplicate_normalized_paths(tmp_path):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("docs/a.md", "one")
        archive.writestr("docs\\a.md", "two")

    with pytest.raises(RagValidationError, match="duplicate"):
        import_zip_bytes(
            archive_name="dupe.zip",
            payload=buffer.getvalue(),
            target_dir=tmp_path / "files",
            config=RagConfig(enabled=True),
        )


def test_import_zip_bytes_rejects_size_budget_overflow(tmp_path):
    payload = _zip_bytes({"big.md": "a" * 2048})

    with pytest.raises(RagValidationError, match="too large"):
        import_zip_bytes(
            archive_name="big.zip",
            payload=payload,
            target_dir=tmp_path / "files",
            config=RagConfig(enabled=True, max_file_size_kb=1),
        )


@pytest.mark.asyncio
async def test_manager_import_zip_source_creates_imported_source_and_indexes(tmp_path):
    payload = _zip_bytes({"guide.md": "# Guide\n\nThe keyword is zipimport."})
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

        result = await manager.import_zip_source(
            archive_name="docs.zip",
            payload=payload,
            collection_id="default",
            name="Docs",
            index=True,
        )

        source = result["source"]
        assert source["mode"] == "imported"
        assert source["name"] == "Docs"
        assert result["import"]["filesImported"] == 1
        assert result["job"]["status"] == "succeeded"
        imported_file = (
            tmp_path
            / "state"
            / "rag"
            / "imports"
            / source["sourceId"]
            / "files"
            / "guide.md"
        )
        assert imported_file.exists()

        search = await manager.search(
            RagSearchRequest(query="zipimport", mode=RagRetrievalMode.FTS)
        )
        assert search["results"][0]["citation"]["label"] == "[来源：guide.md]"
    finally:
        await store.close()
