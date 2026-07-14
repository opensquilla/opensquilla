"""RPC handlers for the local document knowledge base."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from opensquilla.gateway.rpc import RpcContext, RpcHandlerError, get_dispatcher
from opensquilla.gateway.scopes import METHOD_SCOPES
from opensquilla.knowledge.backend import KnowledgeBackend, KnowledgeBackendError
from opensquilla.knowledge.manager import manager_from_config

_d = get_dispatcher()
METHOD_SCOPES["knowledge.settings.get"] = "operator.read"
METHOD_SCOPES["knowledge.settings.patch"] = "operator.admin"
_ALLOWED_BACKEND_ERROR_CODES = frozenset(
    {
        "invalid_retrieval_profile", "retrieval_profile_unavailable",
        "no_retrieval_profile_available", "settings_persist_failed",
    }
)
_RUNTIME_OWNED_STATUS_FIELDS = (
    "connectionState",
    "capabilitiesStale",
    "capabilitiesFetchedAt",
)


def _manager(ctx: RpcContext) -> KnowledgeBackend:
    if ctx.knowledge_runtime is not None:
        return cast(KnowledgeBackend, ctx.knowledge_runtime.current_backend())
    return manager_from_config(getattr(ctx, "config", None))


async def _call_backend[T](
    operation: Callable[..., T],
    *args: Any,
    **kwargs: Any,
) -> T:
    try:
        return await asyncio.to_thread(operation, *args, **kwargs)
    except KnowledgeBackendError as error:
        raise _rpc_backend_error(error) from error


def _rpc_backend_error(error: KnowledgeBackendError) -> RpcHandlerError:
    code = (
        error.code if error.code in _ALLOWED_BACKEND_ERROR_CODES else "KNOWLEDGE_BACKEND_ERROR"
    )
    message = (
        error.message
        if code != "KNOWLEDGE_BACKEND_ERROR"
        else "knowledge service request failed"
    )
    status_code = error.status_code
    retryable = status_code is None or status_code >= 500
    return RpcHandlerError(code, message, retryable=retryable)


def _rpc_unknown_backend_error() -> RpcHandlerError:
    return RpcHandlerError(
        "KNOWLEDGE_BACKEND_ERROR",
        "knowledge service request failed",
    )


def _top_k(params: dict[str, Any], *, default: int = 8) -> int:
    value = params.get("topK", params.get("top_k", default))
    try:
        top_k = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("params.topK must be an integer") from exc
    if top_k < 1 or top_k > 20:
        raise ValueError("params.topK must be between 1 and 20")
    return top_k


def _search_filters(params: dict[str, Any]) -> dict[str, Any] | None:
    filters = params.get("filters")
    if filters is not None and not isinstance(filters, dict):
        raise ValueError("params.filters must be an object")
    merged: dict[str, Any] = dict(filters or {})
    for key in (
        "collectionId",
        "retrievalProfile",
        "embeddingModel",
        "model",
        "embeddingDimensions",
        "dimensions",
    ):
        value = params.get(key)
        if value is not None and value != "":
            merged[key] = value
    return merged or None


@_d.method("knowledge.settings.get", scope="operator.read")
async def _handle_knowledge_settings_get(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    if params is not None and not isinstance(params, dict):
        raise ValueError("params must be an object")
    return await _call_backend(_manager(ctx).settings)


@_d.method("knowledge.settings.patch", scope="operator.admin")
async def _handle_knowledge_settings_patch(
    params: dict | None,
    ctx: RpcContext,
) -> dict[str, Any]:
    if not isinstance(params, dict):
        raise ValueError("params must be an object")
    profile = params.get("defaultRetrievalProfile")
    if not isinstance(profile, str) or not profile.strip():
        raise ValueError("params.defaultRetrievalProfile must be a non-empty string")
    response = await _call_backend(
        _manager(ctx).update_settings,
        {"defaultRetrievalProfile": profile.strip()},
    )
    runtime = ctx.knowledge_runtime
    if runtime is None:
        return response
    runtime.invalidate("settings_updated")
    try:
        await runtime.refresh(force=True, raise_on_error=True)
        snapshot = await runtime.refresh(force=False, raise_on_error=True)
    except asyncio.CancelledError:
        raise
    except KnowledgeBackendError as error:
        raise _rpc_backend_error(error) from error
    except Exception:
        raise _rpc_unknown_backend_error() from None
    if snapshot is None:
        raise _rpc_unknown_backend_error()
    status = snapshot.to_status_wire()
    result = {**status, **response}
    for field in _RUNTIME_OWNED_STATUS_FIELDS:
        if field in status:
            result[field] = status[field]
        else:
            result.pop(field, None)
    return result


@_d.method("knowledge.status", scope="operator.read")
async def _handle_knowledge_status(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    if params is not None and not isinstance(params, dict):
        raise ValueError("params must be an object")
    if ctx.knowledge_runtime is not None:
        return cast(dict[str, Any], ctx.knowledge_runtime.status_payload())
    return await _call_backend(_manager(ctx).status)


@_d.method("knowledge.collections", scope="operator.read")
async def _handle_knowledge_collections(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    if params is not None and not isinstance(params, dict):
        raise ValueError("params must be an object")
    return await _call_backend(_manager(ctx).collections)


@_d.method("knowledge.prepare_sample", scope="operator.admin")
async def _handle_knowledge_prepare_sample(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    if not isinstance(params, dict):
        raise ValueError("params must be an object")
    source_root = params.get("sourceRoot") or params.get("source_root")
    collection_name = params.get("collectionName") or params.get("collection_name")
    limit = params.get("limit", 60)
    try:
        parsed_limit = int(limit)
    except (TypeError, ValueError) as exc:
        raise ValueError("params.limit must be an integer") from exc
    return await _call_backend(
        _manager(ctx).prepare_sample,
        source_root=Path(str(source_root)) if source_root else None,
        limit=parsed_limit,
        collection_name=str(collection_name) if collection_name else None,
    )


@_d.method("knowledge.ingest", scope="operator.admin")
async def _handle_knowledge_ingest(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    if not isinstance(params, dict):
        raise ValueError("params must be an object")
    source_root = params.get("sourceRoot") or params.get("source_root") or params.get("archivePath")
    collection_name = params.get("collectionName") or params.get("collection_name")
    collection_id = params.get("collectionId") or params.get("collection_id")
    index_profiles = params.get("indexProfiles") or params.get("index_profiles")
    if index_profiles is not None and not isinstance(index_profiles, list):
        raise ValueError("params.indexProfiles must be an array")
    limit = params.get("limit", 60)
    try:
        parsed_limit = int(limit)
    except (TypeError, ValueError) as exc:
        raise ValueError("params.limit must be an integer") from exc
    result = await _call_backend(
        _manager(ctx).ingest_collection,
        source_root=Path(str(source_root)) if source_root else None,
        limit=parsed_limit,
        collection_name=str(collection_name) if collection_name else None,
        collection_id=str(collection_id) if collection_id else None,
        index_profiles=[str(item) for item in index_profiles] if index_profiles else None,
    )
    runtime = ctx.knowledge_runtime
    if runtime is not None:
        runtime.invalidate("ingest_completed")
        runtime.request_refresh()
    return result


@_d.method("knowledge.search", scope="operator.read")
async def _handle_knowledge_search(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    if not isinstance(params, dict):
        raise ValueError("params must be an object")
    query = str(params.get("query") or "").strip()
    if not query:
        raise ValueError("params.query is required")
    filters = _search_filters(params)
    top_k = _top_k(params)
    runtime = ctx.knowledge_runtime
    if runtime is not None:
        try:
            return cast(
                dict[str, Any],
                await runtime.call_with_capability_retry(
                    lambda backend: backend.search(
                        query,
                        top_k=top_k,
                        filters=filters,
                    )
                ),
            )
        except KnowledgeBackendError as error:
            raise _rpc_backend_error(error) from error
    return await _call_backend(
        _manager(ctx).search,
        query,
        top_k=top_k,
        filters=filters,
    )


@_d.method("knowledge.get", scope="operator.read")
async def _handle_knowledge_get(params: dict | None, ctx: RpcContext) -> dict[str, Any] | None:
    if not isinstance(params, dict):
        raise ValueError("params must be an object")
    chunk_id = params.get("chunkId") or params.get("chunk_id")
    document_id = params.get("documentId") or params.get("document_id")
    if not chunk_id and not document_id:
        raise ValueError("params.chunkId or params.documentId is required")
    return await _call_backend(
        _manager(ctx).get,
        chunk_id=str(chunk_id) if chunk_id else None,
        document_id=str(document_id) if document_id else None,
    )


@_d.method("knowledge.questions", scope="operator.read")
async def _handle_knowledge_questions(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    if params is not None and not isinstance(params, dict):
        raise ValueError("params must be an object")
    return await _call_backend(_manager(ctx).questions)


@_d.method("knowledge.judgment", scope="operator.write")
async def _handle_knowledge_judgment(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    if not isinstance(params, dict):
        raise ValueError("params must be an object")
    return await _call_backend(_manager(ctx).record_judgment, params)
