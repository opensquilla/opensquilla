from __future__ import annotations

import json

import pytest

from opensquilla.rag.tools import create_rag_tools
from opensquilla.rag.types import RagRetrievalMode
from opensquilla.tools.registry import ToolRegistry
from opensquilla.tools.types import CallerKind, ToolContext


class FakeRagManager:
    def __init__(self) -> None:
        self.search_requests = []

    async def search(self, request):
        self.search_requests.append(request)
        return {
            "query": request.query,
            "mode": request.mode.value if request.mode else None,
            "results": [
                {
                    "content": "local document content",
                    "citation": {"label": "[来源：guide.md]"},
                    "sourceKind": "rag",
                    "untrustedEvidence": True,
                }
            ],
        }

    async def show(self, **_kwargs):
        return {
            "content": "local document content",
            "citation": {"label": "[来源：guide.md]"},
            "sourceKind": "rag",
            "untrustedEvidence": True,
        }


class LargeRagManager:
    async def search(self, request):
        content = "A long local evidence sentence. " * 300
        return {
            "query": request.query,
            "mode": request.mode.value if request.mode else "hybrid",
            "effectiveMode": "hybrid",
            "diagnostics": {
                "durationMs": 12,
                "resultCount": 10,
                "scoring": {
                    "strategy": "weighted_sum",
                    "textWeight": 0.3,
                    "vectorWeight": 0.7,
                    "formula": "score = textWeight * textScore + vectorWeight * vectorScore",
                },
            },
            "results": [
                {
                    "chunkId": f"chk_{idx}",
                    "documentId": f"doc_{idx}",
                    "collectionId": "default",
                    "sourceId": "src_docs",
                    "path": f"docs/{idx}.md",
                    "title": f"Doc {idx}",
                    "content": content,
                    "snippet": f"Snippet {idx}",
                    "score": 0.9,
                    "textScore": 0.8,
                    "vectorScore": 0.95,
                    "retrievalMode": "hybrid",
                    "sourceKind": "rag",
                    "sourceStatus": "active",
                    "untrustedEvidence": True,
                    "citation": {"label": f"[来源：docs/{idx}.md]", "path": f"docs/{idx}.md"},
                    "metadata": {
                        "untrustedEvidence": True,
                        "scoreBreakdown": {
                            "textWeight": 0.3,
                            "vectorWeight": 0.7,
                        },
                    },
                }
                for idx in range(10)
            ],
        }

    async def show(self, **_kwargs):
        return {
            "content": "expanded local document content",
            "truncated": False,
            "citation": {"label": "[来源：guide.md]"},
            "sourceKind": "rag",
            "untrustedEvidence": True,
        }


def test_rag_tools_are_owner_only():
    registry = ToolRegistry()
    create_rag_tools(rag_manager=FakeRagManager(), registry=registry)

    owner_defs = registry.to_tool_definitions(
        ToolContext(is_owner=True, caller_kind=CallerKind.AGENT)
    )
    non_owner_defs = registry.to_tool_definitions(
        ToolContext(is_owner=False, caller_kind=CallerKind.AGENT)
    )

    assert {tool.name for tool in owner_defs} >= {"rag_search", "rag_get"}
    assert "rag_search" not in {tool.name for tool in non_owner_defs}


@pytest.mark.asyncio
async def test_rag_search_tool_marks_untrusted_evidence():
    registry = ToolRegistry()
    create_rag_tools(rag_manager=FakeRagManager(), registry=registry)
    registered = registry.get("rag_search")

    payload = json.loads(await registered.handler(query="guide", mode="fts"))

    assert payload["source_kind"] == "rag"
    assert payload["untrusted_evidence"] is True
    assert payload["results"][0]["citation"]["label"] == "[来源：guide.md]"


@pytest.mark.asyncio
async def test_rag_search_tool_omits_mode_to_use_configured_default():
    registry = ToolRegistry()
    manager = FakeRagManager()
    create_rag_tools(rag_manager=manager, registry=registry)
    registered = registry.get("rag_search")

    payload = json.loads(await registered.handler(query="guide"))

    assert payload["mode"] is None
    assert manager.search_requests[-1].mode is None


@pytest.mark.asyncio
async def test_rag_search_tool_respects_explicit_mode_override():
    registry = ToolRegistry()
    manager = FakeRagManager()
    create_rag_tools(rag_manager=manager, registry=registry)
    registered = registry.get("rag_search")

    payload = json.loads(await registered.handler(query="guide", mode="vector_only"))

    assert payload["mode"] == "vector_only"
    assert manager.search_requests[-1].mode is RagRetrievalMode.VECTOR_ONLY


@pytest.mark.asyncio
async def test_rag_search_tool_returns_compact_evidence_with_strict_budget():
    registry = ToolRegistry()
    create_rag_tools(rag_manager=LargeRagManager(), registry=registry)
    registered = registry.get("rag_search")

    raw = await registered.handler(query="guide", limit=50)
    payload = json.loads(raw)

    assert len(raw) <= 8000
    assert payload["resultFormat"] == "compact_evidence"
    assert payload["payloadBudget"]["maxChars"] == 8000
    assert payload["payloadBudget"]["actualChars"] <= 8000
    assert payload["resultCount"] <= 10
    assert payload["results"]
    first = payload["results"][0]
    assert "content" not in first
    assert first["contentPreview"].endswith("...")
    assert first["citation"]["label"] == "[来源：docs/0.md]"
    assert first["scoreBreakdown"]["textWeight"] == 0.3
    assert first["sourceKind"] == "rag"
    assert first["untrustedEvidence"] is True


def test_rag_tool_budget_class_is_local():
    registry = ToolRegistry()
    create_rag_tools(rag_manager=FakeRagManager(), registry=registry)

    assert registry.get("rag_search").spec.result_budget_class == "local"
    assert registry.get("rag_get").spec.result_budget_class == "local"
