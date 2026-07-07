"""RPC handlers for the local document knowledge base."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from opensquilla.gateway.rpc import RpcContext, get_dispatcher
from opensquilla.knowledge.manager import manager_from_config

_d = get_dispatcher()


def _manager(ctx: RpcContext):
    return manager_from_config(getattr(ctx, "config", None))


def _top_k(params: dict[str, Any], *, default: int = 8) -> int:
    value = params.get("topK", params.get("top_k", default))
    try:
        top_k = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("params.topK must be an integer") from exc
    if top_k < 1 or top_k > 20:
        raise ValueError("params.topK must be between 1 and 20")
    return top_k


@_d.method("knowledge.status", scope="operator.read")
async def _handle_knowledge_status(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    if params is not None and not isinstance(params, dict):
        raise ValueError("params must be an object")
    return _manager(ctx).status()


@_d.method("knowledge.prepare_sample", scope="operator.admin")
async def _handle_knowledge_prepare_sample(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    if not isinstance(params, dict):
        raise ValueError("params must be an object")
    source_root = params.get("sourceRoot") or params.get("source_root")
    limit = params.get("limit", 60)
    try:
        parsed_limit = int(limit)
    except (TypeError, ValueError) as exc:
        raise ValueError("params.limit must be an integer") from exc
    return _manager(ctx).prepare_sample(
        source_root=Path(str(source_root)) if source_root else None,
        limit=parsed_limit,
    )


@_d.method("knowledge.search", scope="operator.read")
async def _handle_knowledge_search(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    if not isinstance(params, dict):
        raise ValueError("params must be an object")
    query = str(params.get("query") or "").strip()
    if not query:
        raise ValueError("params.query is required")
    filters = params.get("filters")
    if filters is not None and not isinstance(filters, dict):
        raise ValueError("params.filters must be an object")
    return _manager(ctx).search(query, top_k=_top_k(params), filters=filters)


@_d.method("knowledge.get", scope="operator.read")
async def _handle_knowledge_get(params: dict | None, ctx: RpcContext) -> dict[str, Any] | None:
    if not isinstance(params, dict):
        raise ValueError("params must be an object")
    chunk_id = params.get("chunkId") or params.get("chunk_id")
    document_id = params.get("documentId") or params.get("document_id")
    if not chunk_id and not document_id:
        raise ValueError("params.chunkId or params.documentId is required")
    return _manager(ctx).get(
        chunk_id=str(chunk_id) if chunk_id else None,
        document_id=str(document_id) if document_id else None,
    )


@_d.method("knowledge.questions", scope="operator.read")
async def _handle_knowledge_questions(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    if params is not None and not isinstance(params, dict):
        raise ValueError("params must be an object")
    return _manager(ctx).questions()


@_d.method("knowledge.judgment", scope="operator.write")
async def _handle_knowledge_judgment(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    if not isinstance(params, dict):
        raise ValueError("params must be an object")
    return _manager(ctx).record_judgment(params)
