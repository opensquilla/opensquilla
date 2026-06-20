"""research_search built-in tool: normalized web search with compact excerpts."""

from __future__ import annotations

import json
from typing import cast

from opensquilla.sandbox.integration import sandboxed
from opensquilla.search.research import run_research_search
from opensquilla.search.types import Recency, SearchMode, SearchOptions
from opensquilla.tools.registry import tool

_VALID_MODES: frozenset[str] = frozenset({"auto", "news", "technical", "broad"})
_VALID_RECENCIES: frozenset[str] = frozenset({"day", "week", "month", "year"})
_VALID_PROVIDERS: frozenset[str] = frozenset(
    {"auto", "tavily", "brave", "duckduckgo", "exa"}
)


def _invalid_request(message: str) -> str:
    return json.dumps(
        {
            "ok": False,
            "error_kind": "invalid_request",
            "error": message,
        },
        ensure_ascii=False,
        indent=2,
    )


def _optional_int(value: object, name: str) -> tuple[int | None, str | None]:
    if value is None:
        return None, None
    if isinstance(value, bool) or not isinstance(value, int):
        return None, f"{name} must be an integer."
    return value, None


def _domain_list(value: object, name: str) -> tuple[tuple[str, ...], str | None]:
    if value is None:
        return (), None
    if not isinstance(value, (list, tuple)) or not all(
        isinstance(item, str) for item in value
    ):
        return (), f"{name} must be a list or tuple of strings."
    return tuple(value), None


@tool(
    name="research_search",
    description=(
        "High-quality web search that deduplicates results and can fetch compact "
        "citation-ready excerpts from the top sources."
    ),
    params={
        "query": {"type": "string", "description": "Search query."},
        "mode": {
            "type": "string",
            "description": "Search mode.",
            "enum": ["auto", "news", "technical", "broad"],
        },
        "max_results": {
            "type": "integer",
            "description": "Maximum number of deduplicated results to return.",
        },
        "fetch_top_k": {
            "type": "integer",
            "description": "Number of top results to fetch for compact excerpts.",
        },
        "max_chars_per_source": {
            "type": "integer",
            "description": "Maximum excerpt characters per source.",
        },
        "include_domains": {
            "type": "array",
            "description": "Optional domains to include.",
            "items": {"type": "string"},
        },
        "exclude_domains": {
            "type": "array",
            "description": "Optional domains to exclude.",
            "items": {"type": "string"},
        },
        "recency": {
            "type": "string",
            "description": "Optional recency filter.",
            "enum": ["day", "week", "month", "year"],
        },
        "provider": {
            "type": "string",
            "description": "Optional provider override.",
            "enum": ["auto", "tavily", "brave", "duckduckgo", "exa"],
        },
    },
    required=["query"],
    result_budget_class="external",
)
@sandboxed(
    kind="web.fetch",
    argv_factory=lambda a: (
        "research_search",
        str(a.get("query", "")),
        str(a.get("fetch_top_k", "")),
    ),
    record_payload=False,
)
async def research_search(
    query: str,
    mode: str = "auto",
    max_results: int | None = None,
    fetch_top_k: int | None = None,
    max_chars_per_source: int | None = None,
    include_domains: list[str] | tuple[str, ...] | None = None,
    exclude_domains: list[str] | tuple[str, ...] | None = None,
    recency: str | None = None,
    provider: str | None = None,
) -> str:
    if not isinstance(query, str) or not query.strip():
        return _invalid_request("query must be a non-empty string.")
    if mode not in _VALID_MODES:
        expected = ", ".join(sorted(_VALID_MODES))
        return _invalid_request(f"Invalid mode. Expected one of: {expected}.")
    if recency is not None and recency not in _VALID_RECENCIES:
        expected = ", ".join(sorted(_VALID_RECENCIES))
        return _invalid_request(f"Invalid recency. Expected one of: {expected}.")
    if provider is not None and provider not in _VALID_PROVIDERS:
        expected = ", ".join(sorted(_VALID_PROVIDERS))
        return _invalid_request(f"Invalid provider. Expected one of: {expected}.")

    resolved_max_results, error = _optional_int(max_results, "max_results")
    if error is not None:
        return _invalid_request(error)
    resolved_fetch_top_k, error = _optional_int(fetch_top_k, "fetch_top_k")
    if error is not None:
        return _invalid_request(error)
    resolved_max_chars, error = _optional_int(
        max_chars_per_source,
        "max_chars_per_source",
    )
    if error is not None:
        return _invalid_request(error)
    resolved_include_domains, error = _domain_list(include_domains, "include_domains")
    if error is not None:
        return _invalid_request(error)
    resolved_exclude_domains, error = _domain_list(exclude_domains, "exclude_domains")
    if error is not None:
        return _invalid_request(error)

    options = SearchOptions(
        query=query,
        mode=cast(SearchMode, mode),
        max_results=10 if resolved_max_results is None else resolved_max_results,
        fetch_top_k=3 if resolved_fetch_top_k is None else resolved_fetch_top_k,
        max_chars_per_source=1500 if resolved_max_chars is None else resolved_max_chars,
        include_domains=resolved_include_domains,
        exclude_domains=resolved_exclude_domains,
        recency=cast(Recency | None, recency),
        provider=None if provider in (None, "auto") else provider,
    )
    payload = await run_research_search(options, fetcher=_research_web_fetcher)
    return json.dumps(payload, ensure_ascii=False, indent=2)


async def _research_web_fetcher(url: str, max_chars: int) -> dict[str, object]:
    from opensquilla.tools.builtin.web_fetch import run_web_fetch_payload

    return await run_web_fetch_payload(url, max_chars=max_chars)
