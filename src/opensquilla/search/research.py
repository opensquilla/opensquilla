"""Offline research search orchestration for future public tool wrappers."""

from __future__ import annotations

import importlib
import re
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from opensquilla.search.normalize import (
    canonicalize_url,
    dedupe_hits_by_canonical_url,
    extract_domain,
)
from opensquilla.search.types import (
    SearchDiagnostics,
    SearchHit,
    SearchOptions,
    SearchProvider,
    SearchProviderError,
    SearchResult,
)

ProviderFactory = Callable[[str], SearchProvider]
Fetcher = Callable[[str, int], Awaitable[Any]]

_DEFAULT_PROVIDER_ORDER = ("tavily", "brave", "duckduckgo")
_FETCH_MIN_USEFUL_CHARS = 240
_EXTERNAL_CONTENT_RE = re.compile(
    r"<external-content\b[^>]*>(?P<content>.*?)</external-content>",
    re.DOTALL | re.IGNORECASE,
)


async def run_research_search(
    options: SearchOptions,
    *,
    provider_factory: ProviderFactory | None = None,
    fetcher: Fetcher | None = None,
    loop_guard: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Search, normalize, dedupe, optionally fetch excerpts, and return JSON-safe payload."""

    diagnostics = SearchDiagnostics(
        query=options.query,
        mode=options.mode,
        loop_guard=dict(loop_guard or {}),
    )

    if not options.query:
        return _failure_payload(
            options,
            diagnostics,
            error_kind="invalid_request",
            error="Search query must not be empty.",
        )

    factory = provider_factory or _default_provider_factory
    provider_names = _provider_order(options)
    selected_provider = ""
    raw_results: list[SearchResult] = []
    terminal_error: Exception | None = None
    explicit_provider = options.provider is not None

    for provider_name in provider_names:
        try:
            provider = factory(provider_name)
            raw_results = await provider.search(options.query, max_results=options.max_results)
        except Exception as exc:  # noqa: BLE001 - orchestrator converts provider failures to payloads
            terminal_error = exc
            search_error = _coerce_search_error(provider_name, exc)
            diagnostics.provider_attempts.append(
                _provider_error_attempt(provider_name, search_error)
            )

            if _should_fallback(search_error, explicit_provider=explicit_provider):
                diagnostics.fallback_from = diagnostics.fallback_from or provider_name
                continue
            return _failure_payload(
                options,
                diagnostics,
                error_kind=search_error.kind,
                error=_public_error_message(provider_name, search_error.kind),
            )

        selected_provider = provider_name
        diagnostics.provider_attempts.append({"provider": provider_name, "status": "success"})
        break

    if not selected_provider:
        search_error = _coerce_search_error(
            provider_names[-1] if provider_names else "unknown",
            terminal_error or RuntimeError("No search provider succeeded."),
        )
        return _failure_payload(
            options,
            diagnostics,
            error_kind=search_error.kind,
            error=_public_error_message(search_error.provider, search_error.kind),
        )

    hits = [_search_result_to_hit(result, selected_provider, options) for result in raw_results]
    hits, diagnostics.duplicate_count = dedupe_hits_by_canonical_url(hits)
    for rank, hit in enumerate(hits, start=1):
        hit.rank = rank

    if options.fetch_top_k > 0:
        await _fetch_compact_excerpts(
            hits,
            options=options,
            diagnostics=diagnostics,
            fetcher=fetcher or _default_fetcher,
        )

    diagnostics.returned_chars = sum(len(hit.excerpt) for hit in hits)
    diagnostics.budget_clamped = any(hit.content_truncated for hit in hits)

    return {
        "ok": True,
        "query": options.query,
        "mode": options.mode,
        "provider_attempts": diagnostics.provider_attempts,
        "diagnostics": _diagnostics_payload(diagnostics),
        "results": [_public_hit_payload(hit) for hit in hits],
    }


def _default_provider_factory(name: str) -> SearchProvider:
    _ensure_builtin_search_providers()
    from opensquilla.search.registry import get_provider

    return get_provider(name)


def _ensure_builtin_search_providers() -> None:
    for module_name in (
        "opensquilla.search.providers.tavily",
        "opensquilla.search.providers.brave",
        "opensquilla.search.providers.duckduckgo",
    ):
        importlib.import_module(module_name)


async def _default_fetcher(url: str, max_chars: int) -> dict[str, Any]:
    from opensquilla.tools.builtin.web_fetch import run_web_fetch_payload

    return await run_web_fetch_payload(url, max_chars=max_chars)


def _provider_order(options: SearchOptions) -> tuple[str, ...]:
    if options.provider:
        if options.provider == "duckduckgo":
            return ("duckduckgo",)
        return (options.provider, "duckduckgo")
    return _DEFAULT_PROVIDER_ORDER


def _coerce_search_error(provider_name: str, exc: Exception) -> SearchProviderError:
    if isinstance(exc, SearchProviderError):
        return exc
    return SearchProviderError(
        provider=provider_name,
        kind="unknown",
        message=str(exc) or exc.__class__.__name__,
        retryable=False,
    )


def _provider_error_attempt(provider_name: str, error: SearchProviderError) -> dict[str, Any]:
    if error.kind == "auth":
        if _is_missing_key_error(error):
            return {"provider": provider_name, "status": "auth_missing"}
        return {"provider": provider_name, "status": "auth_failed"}
    return {"provider": provider_name, "status": "error", "error_kind": error.kind}


def _should_fallback(error: SearchProviderError, *, explicit_provider: bool) -> bool:
    if error.provider == "duckduckgo":
        return False
    if error.kind == "auth":
        return (not explicit_provider) and _is_missing_key_error(error)
    return error.retryable or error.kind in {"network", "timeout", "rate_limit", "http"}


def _is_missing_key_error(error: SearchProviderError) -> bool:
    if error.kind != "auth" or error.status_code is not None:
        return False
    message = error.message.lower()
    return any(
        marker in message
        for marker in (
            "api key not set",
            "key not set",
            "not configured",
            "not set",
            "missing",
            "unset",
        )
    )


def _search_result_to_hit(
    result: SearchResult,
    selected_provider: str,
    options: SearchOptions,
) -> SearchHit:
    excerpt_source = _first_non_empty(result.content, *result.highlights, result.snippet)
    excerpt, truncated = _truncate(excerpt_source, options.max_chars_per_source)
    return SearchHit(
        title=result.title,
        url=result.url,
        canonical_url=_research_canonical_url(result.url),
        domain=extract_domain(result.url),
        provider=result.provider or result.source or selected_provider,
        snippet=result.snippet,
        score=result.score,
        published_at=result.published_at,
        excerpt=excerpt,
        content_truncated=truncated,
        highlights=list(result.highlights),
        raw_metadata=dict(result.raw_metadata),
    )


async def _fetch_compact_excerpts(
    hits: list[SearchHit],
    *,
    options: SearchOptions,
    diagnostics: SearchDiagnostics,
    fetcher: Fetcher,
) -> None:
    for hit in hits[: options.fetch_top_k]:
        if _has_useful_provider_content(hit):
            continue

        try:
            payload = await fetcher(hit.url, options.max_chars_per_source)
        except Exception as exc:  # noqa: BLE001 - fetch failure should not fail search
            hit.fetch_status = exc.__class__.__name__
            diagnostics.fetch_failed_count += 1
            continue

        if not isinstance(payload, dict):
            hit.fetch_status = "malformed_payload"
            diagnostics.fetch_failed_count += 1
            continue

        text = _extract_external_content_text(str(payload.get("text") or ""))
        if not text.strip():
            hit.fetch_status = _fetch_failure_status(payload)
            hit.extractor = str(payload.get("extractor") or "")
            diagnostics.fetch_failed_count += 1
            continue

        excerpt, truncated = _truncate(text, options.max_chars_per_source)
        hit.excerpt = excerpt
        hit.fetched = True
        hit.fetch_status = "ok"
        hit.extractor = str(payload.get("extractor") or "")
        hit.content_truncated = bool(payload.get("truncated")) or truncated
        diagnostics.fetched_count += 1


def _has_useful_provider_content(hit: SearchHit) -> bool:
    return len(hit.excerpt.strip()) >= _FETCH_MIN_USEFUL_CHARS


def _research_canonical_url(url: str) -> str:
    canonical_url = canonicalize_url(url)
    original_path = urlsplit(url).path
    canonical_parts = urlsplit(canonical_url)
    if original_path.endswith("/") and not canonical_parts.path.endswith("/"):
        path = f"{canonical_parts.path}/"
        return urlunsplit(
            (
                canonical_parts.scheme,
                canonical_parts.netloc,
                path,
                canonical_parts.query,
                canonical_parts.fragment,
            )
        )
    return canonical_url


def _extract_external_content_text(text: str) -> str:
    match = _EXTERNAL_CONTENT_RE.search(text)
    if match is None:
        return text.strip()
    return match.group("content").strip()


def _fetch_failure_status(payload: dict[str, Any]) -> str:
    status = payload.get("status")
    if isinstance(status, int) and status >= 400:
        return "http_error"
    if payload.get("error"):
        return "error"
    return "error"


def _first_non_empty(*values: str) -> str:
    for value in values:
        if value.strip():
            return value
    return ""


def _truncate(text: str, max_chars: int) -> tuple[str, bool]:
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars], True


def _failure_payload(
    options: SearchOptions,
    diagnostics: SearchDiagnostics,
    *,
    error_kind: str,
    error: str,
) -> dict[str, Any]:
    diagnostics.returned_chars = 0
    return {
        "ok": False,
        "query": options.query,
        "mode": options.mode,
        "provider_attempts": diagnostics.provider_attempts,
        "diagnostics": _diagnostics_payload(diagnostics),
        "results": [],
        "error_kind": error_kind,
        "error": error,
    }


def _public_error_message(provider: str, kind: str) -> str:
    provider_name = provider or "search provider"
    if kind == "auth":
        return f"{provider_name} search authentication failed. Check provider credentials."
    if kind == "network":
        return f"{provider_name} search network request failed."
    if kind == "timeout":
        return f"{provider_name} search request timed out."
    if kind == "rate_limit":
        return f"{provider_name} search rate limit was reached."
    if kind == "http":
        return f"{provider_name} search request failed."
    return f"{provider_name} search request failed."


def _diagnostics_payload(diagnostics: SearchDiagnostics) -> dict[str, Any]:
    return asdict(diagnostics)


def _public_hit_payload(hit: SearchHit) -> dict[str, Any]:
    payload = asdict(hit)
    payload.pop("raw_metadata", None)
    return payload
