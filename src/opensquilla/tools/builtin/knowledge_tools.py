from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from opensquilla.knowledge.manager import KnowledgeManager, manager_from_config
from opensquilla.tools.registry import tool
from opensquilla.tools.types import ToolError

if TYPE_CHECKING:
    from opensquilla.tools.registry import ToolRegistry


def create_knowledge_tools(
    *,
    manager: KnowledgeManager | None = None,
    registry: ToolRegistry | None = None,
    config: Any | None = None,
) -> None:
    """Register local document-knowledge tools.

    These tools are intentionally independent from OpenSquilla memory. They
    expose operator-indexed local documents as a retrieval source.
    """

    resolved_manager = manager or manager_from_config(config)

    @tool(
        name="knowledge_status",
        description=(
            "Check the local document knowledge base status. Use this before "
            "knowledge_search when you need to know whether local documents are indexed."
        ),
        params={
            "collection": {
                "type": "string",
                "description": (
                    "Optional collection name. The Phase 1 local PoC uses the default collection."
                ),
            }
        },
        registry=registry,
        result_budget_class="compact",
    )
    async def knowledge_status(collection: str | None = None) -> str:
        payload = resolved_manager.status()
        if collection:
            payload["collection"] = collection
        return json.dumps(payload, ensure_ascii=False)

    @tool(
        name="knowledge_search",
        description=(
            "Search the operator-managed local document knowledge base. Return evidence only; "
            "use the snippets and citations as factual support before answering questions "
            "about local financial reports, transcripts, summaries, or uploaded documents."
        ),
        params={
            "query": {
                "type": "string",
                "description": (
                    "The natural-language or keyword query to search in local documents."
                ),
            },
            "collection": {
                "type": "string",
                "description": (
                    "Optional collection name. Defaults to the Phase 1 local collection."
                ),
            },
            "filters": {
                "type": "object",
                "description": "Optional metadata filters such as source or contentKind.",
            },
            "top_k": {
                "type": "integer",
                "minimum": 1,
                "maximum": 20,
                "description": "Maximum evidence results to return.",
            },
        },
        required=["query"],
        registry=registry,
        result_budget_class="evidence",
    )
    async def knowledge_search(
        query: str,
        collection: str | None = None,
        filters: dict[str, Any] | None = None,
        top_k: int = 8,
    ) -> str:
        clean_query = str(query or "").strip()
        if not clean_query:
            raise ToolError("query is required")
        payload = resolved_manager.search(clean_query, top_k=top_k, filters=filters)
        if collection:
            payload["collection"] = collection
        return json.dumps(payload, ensure_ascii=False)

    @tool(
        name="knowledge_get",
        description=(
            "Fetch a full local knowledge chunk by chunk_id or the first chunk of a "
            "document by document_id."
        ),
        params={
            "chunk_id": {
                "type": "string",
                "description": "Knowledge chunk id returned by knowledge_search.",
            },
            "document_id": {
                "type": "string",
                "description": "Knowledge document id returned by knowledge_search.",
            },
        },
        registry=registry,
        result_budget_class="evidence",
    )
    async def knowledge_get(
        chunk_id: str | None = None,
        document_id: str | None = None,
    ) -> str:
        if not chunk_id and not document_id:
            raise ToolError("chunk_id or document_id is required")
        payload = resolved_manager.get(chunk_id=chunk_id, document_id=document_id)
        if payload is None:
            raise ToolError("knowledge item not found")
        return json.dumps(payload, ensure_ascii=False)
