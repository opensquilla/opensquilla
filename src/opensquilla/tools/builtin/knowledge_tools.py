from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

from opensquilla.knowledge.backend import KnowledgeBackend, KnowledgeBackendError
from opensquilla.knowledge.manager import manager_from_config
from opensquilla.tools.registry import tool
from opensquilla.tools.types import ToolError, current_tool_context

if TYPE_CHECKING:
    from opensquilla.knowledge.runtime import KnowledgeRuntime
    from opensquilla.tools.registry import ToolRegistry


def _merged_search_filters(
    *,
    filters: dict[str, Any] | None,
    collection: str | None,
    collection_id: str | None,
    retrieval_profile: str | None,
    embedding_model: str | None,
    embedding_dimensions: int | None,
) -> dict[str, Any] | None:
    merged: dict[str, Any] = dict(filters or {})
    resolved_collection = str(collection_id or collection or "").strip()
    if resolved_collection:
        merged["collectionId"] = resolved_collection
    resolved_profile = str(retrieval_profile or "").strip()
    if resolved_profile:
        merged["retrievalProfile"] = resolved_profile
    resolved_model = str(embedding_model or "").strip()
    if resolved_model:
        merged["embeddingModel"] = resolved_model
    if embedding_dimensions is not None:
        merged["embeddingDimensions"] = int(embedding_dimensions)
    return merged or None


def create_knowledge_tools(
    *,
    manager: KnowledgeBackend | None = None,
    runtime: KnowledgeRuntime | None = None,
    registry: ToolRegistry | None = None,
    config: Any | None = None,
) -> None:
    """Register local document-knowledge tools.

    These tools are intentionally independent from OpenSquilla memory. They
    expose operator-indexed local documents as a retrieval source.
    """

    def current_manager() -> KnowledgeBackend:
        if runtime is not None:
            return runtime.current_backend()
        return manager if manager is not None else manager_from_config(config)

    @tool(
        name="knowledge_status",
        description=(
            "Check the local document knowledge base status, including available "
            "retrievalProfiles when the backend exposes them. Use this before "
            "knowledge_search when selecting lexical, vector, or hybrid retrieval."
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
        if runtime is not None:
            payload = runtime.status_payload()
        else:
            payload = await asyncio.to_thread(current_manager().status)
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
            "collection_id": {
                "type": "string",
                "description": (
                    "Optional collection id to filter search results. Overrides collection "
                    "when both are provided."
                ),
            },
            "retrieval_profile": {
                "type": "string",
                "description": (
                    "Optional one-request override. Omit to use the Knowledge service default."
                ),
            },
            "filters": {
                "type": "object",
                "description": (
                    "Optional metadata filters such as source or contentKind. collection_id "
                    "and retrieval_profile are merged into this object when provided."
                ),
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
        collection_id: str | None = None,
        retrieval_profile: str | None = None,
        embedding_model: str | None = None,
        embedding_dimensions: int | None = None,
        filters: dict[str, Any] | None = None,
        top_k: int = 8,
    ) -> str:
        clean_query = str(query or "").strip()
        if not clean_query:
            raise ToolError("query is required")
        context = current_tool_context.get()
        snapshot = getattr(context, "knowledge_capability_snapshot", None)
        state = (
            "LEGACY"
            if context is None
            else getattr(getattr(snapshot, "state", None), "value", None)
        )
        if state not in {"READY", "DEGRADED", "LEGACY"}:
            raise ToolError("knowledge_search_unavailable")
        filter_profile = (
            filters.get("retrievalProfile") if isinstance(filters, dict) else None
        )
        resolved_profile = str(retrieval_profile or filter_profile or "").strip()
        if resolved_profile and (
            state != "READY"
            or resolved_profile
            not in getattr(snapshot, "available_profile_ids", ())
        ):
            raise ToolError("retrieval_profile_unavailable")
        merged_filters = _merged_search_filters(
            filters=filters,
            collection=collection,
            collection_id=collection_id,
            retrieval_profile=retrieval_profile,
            embedding_model=embedding_model,
            embedding_dimensions=embedding_dimensions,
        )

        def search(backend: KnowledgeBackend) -> dict[str, Any]:
            return backend.search(
                clean_query,
                top_k=top_k,
                filters=merged_filters,
            )

        try:
            capability_retry = getattr(runtime, "call_with_capability_retry", None)
            if callable(capability_retry):
                payload = await capability_retry(search)
            else:
                payload = await asyncio.to_thread(search, current_manager())
        except KnowledgeBackendError as error:
            backend_code = error.code or "unknown"
            raise ToolError(
                f"knowledge_search_failed (backend_code={backend_code})"
            ) from None
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
        payload = await asyncio.to_thread(
            current_manager().get,
            chunk_id=chunk_id,
            document_id=document_id,
        )
        if payload is None:
            raise ToolError("knowledge item not found")
        return json.dumps(payload, ensure_ascii=False)
