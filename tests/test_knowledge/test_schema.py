from __future__ import annotations

import sqlite3
from pathlib import Path

from opensquilla.knowledge.index import KnowledgeIndex


def test_knowledge_schema_creates_pipeline_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "knowledge.db"
    index = KnowledgeIndex(db_path)

    index.initialize()

    with sqlite3.connect(db_path) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'virtual table')"
            )
        }

    assert {
        "collections",
        "source_files",
        "documents",
        "document_profiles",
        "processing_plans",
        "artifacts",
        "chunks",
        "chunk_lineage",
        "index_builds",
        "index_catalog",
        "fts_chunks",
    }.issubset(tables)
