from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from opensquilla.gateway.rpc import RpcContext, get_dispatcher


@pytest.mark.asyncio
async def test_knowledge_rpc_prepare_search_and_judgment(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    (source_root / "report.md").write_text(
        "# AI 玻璃材料\n\n康宁公司的 AI 基建玻璃材料需求正在提升。",
        encoding="utf-8",
    )
    ctx = RpcContext(
        conn_id="test",
        config=SimpleNamespace(state_dir=str(tmp_path / "state")),
    )

    dispatcher = get_dispatcher()
    prepare = await dispatcher.dispatch(
        "1",
        "knowledge.prepare_sample",
        {"sourceRoot": str(source_root), "limit": 5},
        ctx,
    )
    assert prepare.ok is True
    assert prepare.payload["documentsIndexed"] == 1

    search = await dispatcher.dispatch(
        "2",
        "knowledge.search",
        {"query": "康宁 AI 玻璃材料", "topK": 3},
        ctx,
    )
    assert search.ok is True
    assert search.payload["results"]
    assert search.payload["results"][0]["citation"]
    assert search.payload["results"][0]["collectionId"] == "default"

    collections = await dispatcher.dispatch("2b", "knowledge.collections", {}, ctx)
    assert collections.ok is True
    assert collections.payload["collections"][0]["collectionId"] == "default"

    questions = await dispatcher.dispatch("3", "knowledge.questions", {}, ctx)
    assert questions.ok is True
    assert questions.payload["questions"]

    judgment = await dispatcher.dispatch(
        "4",
        "knowledge.judgment",
        {
            "questionId": "q001",
            "question": "康宁公司的核心观点是什么？",
            "rating": "correct",
            "evidence": "supported",
            "hallucination": "none",
        },
        ctx,
    )
    assert judgment.ok is True
    path = tmp_path / "state" / "knowledge" / "data" / "eval" / "judgments.jsonl"
    assert json.loads(path.read_text(encoding="utf-8").splitlines()[0])["rating"] == "correct"
