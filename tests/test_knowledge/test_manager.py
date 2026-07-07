from __future__ import annotations

import json
from pathlib import Path

from opensquilla.knowledge.manager import KnowledgeManager


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
