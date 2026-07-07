from __future__ import annotations

import json
from pathlib import Path

import pytest

from opensquilla.knowledge.manager import KnowledgeManager
from opensquilla.tools.builtin.knowledge_tools import create_knowledge_tools
from opensquilla.tools.registry import ToolRegistry


@pytest.mark.asyncio
async def test_knowledge_tools_register_and_search(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    (source_root / "report.md").write_text(
        "# AI 光通信\n\n光模块需求受 AI 算力建设带动，资本开支是关键变量。",
        encoding="utf-8",
    )
    manager = KnowledgeManager(tmp_path / "knowledge")
    manager.prepare_sample(source_root=source_root, limit=5)

    registry = ToolRegistry()
    create_knowledge_tools(manager=manager, registry=registry)

    assert {"knowledge_status", "knowledge_search", "knowledge_get"}.issubset(
        set(registry.list_names())
    )

    search_tool = registry.get("knowledge_search")
    assert search_tool is not None
    payload = json.loads(await search_tool.handler(query="AI 光通信", top_k=3))

    assert payload["results"]
    assert payload["results"][0]["chunkId"]

    get_tool = registry.get("knowledge_get")
    assert get_tool is not None
    chunk_id = payload["results"][0]["chunkId"]
    detail = json.loads(await get_tool.handler(chunk_id=chunk_id))
    assert detail["chunkId"] == chunk_id
