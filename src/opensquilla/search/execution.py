"""Search status and query execution helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from opensquilla.safety.sensitive_payloads import (
    sensitive_body_block,
    sensitive_body_marker,
)
from opensquilla.search import runtime as search_runtime
from opensquilla.search.types import SearchProviderError, SearchResult


def _format_search_error(provider_name: str, exc: Exception) -> tuple[str, str]:
    error_class = type(exc).__name__
    raw = str(exc).strip()
    if raw:
        return error_class, raw
    if error_class == "ConnectTimeout":
        return (
            error_class,
            (
                f"{provider_name} search request timed out. Configure search_proxy "
                "or switch search_provider to duckduckgo."
            ),
        )
    return error_class, f"{provider_name} search failed with {error_class}."


def _ensure_builtin_search_providers() -> None:
    import opensquilla.search.providers.brave  # noqa: F401
    import opensquilla.search.providers.duckduckgo  # noqa: F401


def _search_provider_kwargs(provider_name: str) -> dict[str, object]:
    return search_runtime.search_provider_kwargs(provider_name)


def _search_success_payload(payload: dict[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    result["ok"] = True
    if "fallback_from" in result:
        result["fallbackFrom"] = result["fallback_from"]
    return result


def _search_failure_payload(
    payload: dict[str, Any],
    *,
    retryable: bool = False,
) -> dict[str, Any]:
    result = dict(payload)
    message = str(result.get("error") or "")
    error_kind = str(result.get("error_kind") or "unknown")
    error_class = str(result.get("error_class") or "")
    result["ok"] = False
    result["errorMessage"] = message
    result["error"] = {
        "kind": error_kind,
        "class": error_class,
        "message": message,
        "retryable": retryable,
    }
    return result


def search_runtime_status(provider_name: str | None = None) -> dict[str, Any]:
    from opensquilla.search.registry import get_provider, get_provider_spec

    _ensure_builtin_search_providers()
    runtime = search_runtime.current_search_runtime()
    provider = provider_name or runtime.provider_name
    spec = get_provider_spec(provider)
    api_key_configured = search_runtime.is_search_api_key_configured(provider)
    configured = (not spec.requires_api_key) or api_key_configured
    error: str | None = None
    buildable = False
    try:
        get_provider(provider, **_search_provider_kwargs(provider))
        buildable = True
    except Exception as exc:  # noqa: BLE001 - diagnostic surface
        error = str(exc)
    return {
        "activeProvider": runtime.provider_name,
        "provider": provider,
        "configured": configured,
        "runtimeSupported": spec.runtime_supported,
        "requiresApiKey": spec.requires_api_key,
        "apiKeyConfigured": api_key_configured,
        "maxResults": runtime.max_results,
        "proxyConfigured": bool(runtime.proxy),
        "useEnvProxy": bool(runtime.use_env_proxy),
        "fallbackPolicy": runtime.fallback_policy,
        "diagnostics": bool(runtime.diagnostics),
        "buildable": buildable,
        "error": error,
    }


def search_provider_payload() -> dict[str, str]:
    return {"provider": search_runtime.get_active_provider()}


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


async def run_search_payload(
    query: str,
    max_results: int | None = None,
    *,
    provider_name: str | None = None,
) -> dict[str, Any]:
    from opensquilla.search.registry import get_provider

    _ensure_builtin_search_providers()
    runtime = search_runtime.current_search_runtime()
    provider_name = provider_name or runtime.provider_name
    marker = sensitive_body_marker(query)
    if marker is not None:
        return _search_failure_payload(
            {
                "query": "[redacted]",
                "provider": provider_name,
                "results": [],
                "error_class": "SensitiveInput",
                "error": sensitive_body_block("web_search", marker),
                "error_kind": "invalid_request",
            },
            retryable=False,
        )

    limit = max_results or runtime.max_results
    attempts: list[dict[str, str]] | None = [] if runtime.diagnostics else None
    try:
        provider = get_provider(
            provider_name,
            **_search_provider_kwargs(provider_name),
        )
        results = await provider.search(query, max_results=limit)
        if attempts is not None:
            attempts.append({"provider": provider_name, "status": "success"})
        return _search_success_payload(_search_payload(query, provider_name, results))
    except Exception as exc:
        classified = _classify_search_error(provider_name, exc)
        if attempts is not None:
            attempts.append(
                {
                    "provider": provider_name,
                    "status": "error",
                    "error_kind": classified.kind if classified else "unknown",
                }
            )

        should_fallback = (
            runtime.fallback_policy == "network"
            and provider_name != "duckduckgo"
            and classified is not None
            and classified.kind in {"timeout", "network"}
        )
        if should_fallback:
            try:
                fallback_provider = get_provider(
                    "duckduckgo",
                    **_search_provider_kwargs("duckduckgo"),
                )
                results = await fallback_provider.search(query, max_results=limit)
                if attempts is not None:
                    attempts.append({"provider": "duckduckgo", "status": "success"})
                return _search_success_payload(
                    _search_payload(
                        query,
                        "duckduckgo",
                        fallback_from=provider_name,
                        attempts=attempts,
                        results=results,
                    )
                )
            except Exception as fallback_exc:
                if attempts is not None:
                    fallback_classified = _classify_search_error("duckduckgo", fallback_exc)
                    attempts.append(
                        {
                            "provider": "duckduckgo",
                            "status": "error",
                            "error_kind": (
                                fallback_classified.kind if fallback_classified else "unknown"
                            ),
                        }
                    )

        return _search_failure_payload(
            _search_error_payload(query, provider_name, exc, attempts=attempts),
            retryable=bool(classified and classified.retryable),
        )


def _classify_search_error(provider_name: str, exc: Exception) -> SearchProviderError | None:
    if isinstance(exc, SearchProviderError):
        return exc
    if isinstance(exc, httpx.TimeoutException):
        return SearchProviderError(
            provider=provider_name,
            kind="timeout",
            message=str(exc) or "Search request timed out.",
            retryable=True,
        )
    if isinstance(exc, httpx.NetworkError):
        return SearchProviderError(
            provider=provider_name,
            kind="network",
            message=str(exc) or "Search network request failed.",
            retryable=True,
        )
    return None


def _search_payload(
    query: str,
    provider_name: str,
    results: list[SearchResult],
    *,
    fallback_from: str = "",
    attempts: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "query": query,
        "provider": provider_name,
        "results": [{"title": r.title, "url": r.url, "snippet": r.snippet} for r in results],
    }
    if fallback_from:
        payload["fallback_from"] = fallback_from
    if attempts is not None:
        payload["attempts"] = attempts
    return payload


def _search_error_payload(
    query: str,
    provider_name: str,
    exc: Exception,
    *,
    attempts: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    error_class, error_message = _format_search_error(provider_name, exc)
    payload: dict[str, Any] = {
        "query": query,
        "provider": provider_name,
        "results": [],
        "error_class": error_class,
        "error": error_message,
    }
    classified = _classify_search_error(provider_name, exc)
    if classified is not None:
        payload["error_kind"] = classified.kind
    if attempts is not None:
        payload["attempts"] = attempts
    return payload
