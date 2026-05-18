"""RPC wire payload helpers for the search domain."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from opensquilla.search import runtime as search_runtime
from opensquilla.search.execution import run_search_payload, search_runtime_status


def search_provider_payload() -> dict[str, str]:
    return {"provider": search_runtime.get_active_provider()}


def _search_status_rpc_params(params: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if params is None:
        return {}
    if not isinstance(params, Mapping):
        raise ValueError("params must be an object")
    return params


def search_status_rpc_payload(params: Mapping[str, Any] | None) -> dict[str, Any]:
    """Build the RPC wire payload for a search status request."""

    raw = _search_status_rpc_params(params)
    provider = raw.get("provider")
    return search_runtime_status(str(provider) if provider else None)


def _query_limit_from_params(params: Mapping[str, Any]) -> int | None:
    if "limit" not in params or params.get("limit") is None:
        return None
    try:
        limit = int(params["limit"])
    except (TypeError, ValueError) as exc:
        raise ValueError("params.limit must be an integer") from exc
    if limit < 1 or limit > 20:
        raise ValueError("params.limit must be between 1 and 20")
    return limit


def _search_rpc_payload(
    payload: dict[str, Any],
    *,
    query: str,
    provider_name: str | None,
) -> dict[str, Any]:
    provider = payload.get("provider", provider_name or search_runtime.get_active_provider())
    if payload.get("ok", False):
        result = {
            "ok": True,
            "query": payload.get("query", query),
            "provider": provider,
            "results": payload.get("results", []),
        }
        if payload.get("fallbackFrom"):
            result["fallbackFrom"] = payload.get("fallbackFrom")
        if payload.get("attempts") is not None:
            result["attempts"] = payload.get("attempts")
        return result

    error = payload.get("error")
    if not isinstance(error, dict):
        error = {
            "kind": payload.get("error_kind", "unknown"),
            "class": payload.get("error_class", ""),
            "message": str(payload.get("error") or ""),
            "retryable": False,
        }
    result = {
        "ok": False,
        "query": payload.get("query", query),
        "provider": provider,
        "results": payload.get("results", []),
        "error": error,
    }
    if payload.get("attempts") is not None:
        result["attempts"] = payload.get("attempts")
    return result


async def search_query_rpc_payload(params: Mapping[str, Any] | None) -> dict[str, Any]:
    """Build the RPC wire payload for a search query request."""

    if not isinstance(params, Mapping):
        raise ValueError("params must be an object")
    query = str(params.get("query") or "").strip()
    if not query:
        raise ValueError("params.query is required")
    provider = params.get("provider")
    provider_name = str(provider) if provider else None
    if provider_name:
        search_runtime_status(provider_name)
    payload = await run_search_payload(
        query,
        _query_limit_from_params(params),
        provider_name=provider_name,
    )
    return _search_rpc_payload(payload, query=query, provider_name=provider_name)
