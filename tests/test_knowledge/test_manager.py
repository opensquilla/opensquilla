from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from opensquilla.knowledge.manager import KnowledgeManager, manager_from_config


def test_manager_prepares_markdown_sample_and_eval_questions(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    report_dir = source_root / "ace-camp"
    report_dir.mkdir(parents=True)
    (report_dir / "2026-06-20+康宁公司AI玻璃材料.md").write_text(
        "# 康宁公司AI玻璃材料\n\n康宁公司的 AI 基建玻璃材料需求正在提升。\n\n"
        "光通信产业链的资本开支仍然是核心变量。",
        encoding="utf-8",
    )
    (report_dir / "2026-06-21+动力电池库存.md").write_text(
        "# 动力电池库存\n\n动力电池库存去化仍需时间，价格压力存在。",
        encoding="utf-8",
    )

    manager = KnowledgeManager(tmp_path / "knowledge")
    summary = manager.prepare_sample(source_root=source_root, limit=10)

    assert summary["documentsIndexed"] == 2
    assert summary["chunksIndexed"] >= 2
    assert (tmp_path / "knowledge" / "data" / "sample_manifest.jsonl").exists()
    assert (tmp_path / "knowledge" / "data" / "eval" / "golden_queries.jsonl").exists()
    assert (tmp_path / "knowledge" / "reports" / "parser_report.md").exists()

    results = manager.search("康宁 AI 玻璃材料", top_k=5)["results"]
    assert results
    assert results[0]["documentId"]
    assert "康宁" in results[0]["snippet"]

    questions = [
        json.loads(line)
        for line in (tmp_path / "knowledge" / "data" / "eval" / "golden_queries.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert len(questions) >= 2
    assert all("question" in row for row in questions)


def test_manager_records_pipeline_plan_lineage_and_html(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    (source_root / "report.md").write_text(
        "# AI 玻璃材料\n\n康宁公司的 AI 基建玻璃材料需求正在提升。",
        encoding="utf-8",
    )
    (source_root / "brief.html").write_text(
        "<html><head><title>光模块简报</title></head>"
        "<body><main><h1>光模块</h1><p>光模块需求受 AI 算力建设带动。</p></main></body></html>",
        encoding="utf-8",
    )
    manager = KnowledgeManager(tmp_path / "knowledge")

    summary = manager.prepare_sample(source_root=source_root, limit=10, collection_name="research")

    assert summary["collectionId"] == "default"
    assert summary["documentsIndexed"] == 2
    collections = manager.collections()["collections"]
    assert collections[0]["documentsIndexed"] == 2

    html_results = manager.search("光模块 AI 算力", top_k=5)["results"]
    assert html_results
    html_detail = manager.get(chunk_id=html_results[0]["chunkId"])
    assert html_detail is not None
    assert html_detail["preprocessorStrategy"] in {"html_readability_v1", "markdown_text_v1"}
    assert html_detail["lineage"]
    assert {step["operation"] for step in html_detail["lineage"]} >= {
        "preprocess",
        "chunk",
        "index",
    }


def test_manager_records_judgment_jsonl(tmp_path: Path) -> None:
    manager = KnowledgeManager(tmp_path / "knowledge")

    saved = manager.record_judgment(
        {
            "questionId": "q001",
            "question": "康宁公司的核心观点是什么？",
            "rating": "correct",
            "evidence": "supported",
            "hallucination": "none",
            "notes": "证据充分",
        }
    )

    assert saved["ok"] is True
    judgment_path = tmp_path / "knowledge" / "data" / "eval" / "judgments.jsonl"
    rows = [json.loads(line) for line in judgment_path.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["questionId"] == "q001"
    assert rows[0]["rating"] == "correct"


def test_manager_from_config_local_backend_supports_settings_contract(
    tmp_path: Path,
) -> None:
    configs = [
        SimpleNamespace(state_dir=tmp_path / "default-state"),
        SimpleNamespace(
            state_dir=tmp_path / "explicit-state",
            knowledge=SimpleNamespace(
                enabled=True,
                backend="local",
                local_root_dir=str(tmp_path / "explicit-knowledge"),
            ),
        ),
    ]

    for config in configs:
        manager = manager_from_config(config)
        assert isinstance(manager, KnowledgeManager)
        assert manager.settings() == {
            "defaultRetrievalProfile": "sqlite_fts5_default",
        }
        assert manager.update_settings(
            {"defaultRetrievalProfile": "sqlite_fts5_default"}
        ) == {
            "configuredDefaultRetrievalProfile": "sqlite_fts5_default",
            "effectiveDefaultRetrievalProfile": "sqlite_fts5_default",
        }
        assert manager.settings() == {
            "defaultRetrievalProfile": "sqlite_fts5_default",
        }


def test_local_manager_rejects_unsupported_settings(tmp_path: Path) -> None:
    manager = manager_from_config(
        SimpleNamespace(
            state_dir=tmp_path,
            knowledge=SimpleNamespace(enabled=True, backend="local", local_root_dir=None),
        )
    )

    for payload in (
        {},
        {"defaultRetrievalProfile": ""},
        {"defaultRetrievalProfile": "hybrid_rrf_bge_m3_fts5"},
    ):
        with pytest.raises(
            ValueError,
            match="local knowledge backend only supports sqlite_fts5_default",
        ):
            manager.update_settings(payload)

    assert manager.settings() == {
        "defaultRetrievalProfile": "sqlite_fts5_default",
    }
