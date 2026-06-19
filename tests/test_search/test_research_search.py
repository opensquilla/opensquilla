from __future__ import annotations

from typing import Any

import pytest

from opensquilla.search.research import run_research_search
from opensquilla.search.types import SearchOptions, SearchProviderError, SearchResult


class FakeProvider:
    name = "tavily"

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        return [
            SearchResult(
                title="Python release",
                url="https://www.python.org/downloads/release/python-3135/?utm_source=x",
                snippet="Python release announcement",
                provider="tavily",
                source="tavily",
                published_at="2026-06-11",
                score=0.9,
                content="Python release announcement with enough content for an excerpt.",
            ),
            SearchResult(
                title="Duplicate",
                url="https://www.python.org/downloads/release/python-3135/#notes",
                snippet="Duplicate announcement",
                provider="tavily",
                source="tavily",
            ),
        ][:max_results]


class AuthFailProvider:
    name = "tavily"

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        raise SearchProviderError("tavily", "auth", "Tavily auth failed", retryable=False)


class MissingKeyAuthProvider:
    name = "tavily"

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        raise SearchProviderError(
            "tavily",
            "auth",
            "Tavily API key not set",
            retryable=False,
            status_code=None,
        )


class ConfiguredBadKeyAuthProvider:
    name = "tavily"

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        raise SearchProviderError(
            "tavily",
            "auth",
            "raw secret sk-test leaked",
            retryable=False,
            status_code=401,
        )


class SensitiveErrorProvider:
    name = "tavily"

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        raise SearchProviderError(
            "tavily",
            "http",
            "secret token sk-test url https://example.com?api_key=abc raw body",
            retryable=False,
        )


class ShortContentProvider:
    name = "tavily"

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        return [
            SearchResult(
                title="Fetched source",
                url="https://example.com/article",
                snippet="Short provider snippet.",
                provider="tavily",
                source="tavily",
                content="Tiny.",
            )
        ][:max_results]


class SnippetProvider:
    name = "tavily"

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        return [
            SearchResult(
                title="Fallback source",
                url="https://example.com/fallback",
                snippet="Provider snippet remains available.",
                provider="tavily",
                source="tavily",
            )
        ][:max_results]


class NetworkFailProvider:
    name = "tavily"

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        raise SearchProviderError("tavily", "network", "Network failed", retryable=True)


class FallbackProvider:
    name = "duckduckgo"

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        return [
            SearchResult(
                title="Fallback result",
                url="https://example.org/result",
                snippet="Fallback snippet",
                provider="duckduckgo",
                source="duckduckgo",
            )
        ][:max_results]


class UsefulTopResultsProvider:
    name = "tavily"

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        useful_content = "Useful provider content. " * 12
        return [
            SearchResult(
                title="Useful first",
                url="https://example.com/first",
                snippet="First snippet",
                provider="tavily",
                source="tavily",
                content=useful_content,
            ),
            SearchResult(
                title="Useful second",
                url="https://example.com/second",
                snippet="Second snippet",
                provider="tavily",
                source="tavily",
                content=useful_content,
            ),
            SearchResult(
                title="Short third",
                url="https://example.com/third",
                snippet="Third snippet",
                provider="tavily",
                source="tavily",
                content="Short.",
            ),
        ][:max_results]


class DomainFilteringProvider:
    name = "tavily"

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        return [
            SearchResult(
                title="Allowed exact",
                url="https://python.org/about",
                snippet="Allowed exact domain",
                provider="tavily",
                source="tavily",
                content="Short.",
            ),
            SearchResult(
                title="Allowed subdomain",
                url="https://www.python.org/downloads",
                snippet="Allowed subdomain",
                provider="tavily",
                source="tavily",
                content="Short.",
            ),
            SearchResult(
                title="Blocked suffix lookalike",
                url="https://notpython.org/article",
                snippet="Must not match python.org",
                provider="tavily",
                source="tavily",
                content="Short.",
            ),
            SearchResult(
                title="Excluded docs",
                url="https://docs.python.org/3/",
                snippet="Explicitly excluded subdomain",
                provider="tavily",
                source="tavily",
                content="Short.",
            ),
        ][:max_results]


class RecencyAwareProvider:
    name = "tavily"

    def __init__(self, calls: list[tuple[str, dict[str, Any]]]) -> None:
        self._calls = calls

    async def search(
        self,
        query: str,
        max_results: int = 5,
        *,
        recency: str | None = None,
    ) -> list[SearchResult]:
        self._calls.append((query, {"max_results": max_results, "recency": recency}))
        return [
            SearchResult(
                title="Fresh result",
                url="https://example.com/fresh",
                snippet="Fresh snippet",
                provider="tavily",
                source="tavily",
            )
        ]


@pytest.mark.asyncio
async def test_research_search_dedupes_and_uses_provider_content_without_fetch() -> None:
    payload = await run_research_search(
        SearchOptions(query="python release", max_results=5, fetch_top_k=0),
        provider_factory=lambda name: FakeProvider(),
    )

    assert payload["ok"] is True
    assert payload["query"] == "python release"
    assert payload["results"][0]["provider"] == "tavily"
    assert payload["results"][0]["domain"] == "www.python.org"
    assert (
        payload["results"][0]["canonical_url"]
        == "https://www.python.org/downloads/release/python-3135/"
    )
    assert payload["results"][0]["published_at"] == "2026-06-11"
    assert payload["results"][0]["rank"] == 1
    assert payload["diagnostics"]["duplicate_count"] == 1
    assert payload["results"][0]["excerpt"].startswith("Python release announcement")
    assert payload["results"][0]["fetched"] is False
    assert "raw_metadata" not in payload["results"][0]


@pytest.mark.asyncio
async def test_research_search_primary_auth_failure_does_not_silent_fallback() -> None:
    payload = await run_research_search(
        SearchOptions(query="python release", provider="tavily"),
        provider_factory=lambda name: AuthFailProvider(),
    )

    assert payload["ok"] is False
    assert payload["error_kind"] == "auth"
    assert payload["provider_attempts"] == [{"provider": "tavily", "status": "auth_failed"}]


@pytest.mark.asyncio
async def test_research_search_missing_key_auth_can_fallback_in_auto_mode() -> None:
    def provider_factory(name: str) -> MissingKeyAuthProvider | FallbackProvider:
        if name in {"tavily", "brave"}:
            return MissingKeyAuthProvider()
        return FallbackProvider()

    payload = await run_research_search(
        SearchOptions(query="q", fetch_top_k=0),
        provider_factory=provider_factory,
    )

    assert payload["ok"] is True
    assert payload["provider_attempts"] == [
        {"provider": "tavily", "status": "auth_missing"},
        {"provider": "brave", "status": "auth_missing"},
        {"provider": "duckduckgo", "status": "success"},
    ]


@pytest.mark.asyncio
async def test_research_search_configured_auth_failure_does_not_fallback_or_leak() -> None:
    def provider_factory(name: str) -> ConfiguredBadKeyAuthProvider | FallbackProvider:
        if name == "tavily":
            return ConfiguredBadKeyAuthProvider()
        return FallbackProvider()

    payload = await run_research_search(
        SearchOptions(query="q", fetch_top_k=0),
        provider_factory=provider_factory,
    )

    assert payload["ok"] is False
    assert payload["error_kind"] == "auth"
    assert payload["provider_attempts"] == [{"provider": "tavily", "status": "auth_failed"}]
    assert "sk-test" not in payload["error"]
    assert "raw secret sk-test leaked" not in payload["error"]


@pytest.mark.asyncio
async def test_research_search_public_error_message_is_sanitized() -> None:
    payload = await run_research_search(
        SearchOptions(query="q", provider="tavily", fetch_top_k=0),
        provider_factory=lambda name: SensitiveErrorProvider(),
    )

    assert payload["ok"] is False
    assert payload["error_kind"] == "http"
    assert len(payload["error"]) < 120
    assert "sk-test" not in payload["error"]
    assert "api_key=abc" not in payload["error"]
    assert "raw body" not in payload["error"]


@pytest.mark.asyncio
async def test_research_search_fetches_compact_excerpt_for_short_provider_content() -> None:
    async def fetcher(url: str, max_chars: int) -> dict[str, Any]:
        return {
            "text": (
                '<external-content source="https://example.com">'
                "Fetched body text"
                "</external-content>"
            ),
            "extractor": "readability",
            "truncated": False,
            "status": 200,
        }

    payload = await run_research_search(
        SearchOptions(query="q", fetch_top_k=1, max_chars_per_source=500),
        provider_factory=lambda name: ShortContentProvider(),
        fetcher=fetcher,
    )

    assert payload["ok"] is True
    assert payload["results"][0]["fetched"] is True
    assert payload["results"][0]["fetch_status"] == "ok"
    assert payload["results"][0]["extractor"] == "readability"
    assert "Fetched body text" in payload["results"][0]["excerpt"]
    assert payload["diagnostics"]["fetched_count"] == 1


@pytest.mark.asyncio
async def test_research_search_keeps_provider_excerpt_when_fetch_fails() -> None:
    async def fetcher(url: str, max_chars: int) -> dict[str, Any]:
        return {"error": "blocked", "status": 403, "extractor": "none", "text": ""}

    payload = await run_research_search(
        SearchOptions(query="q", fetch_top_k=1),
        provider_factory=lambda name: SnippetProvider(),
        fetcher=fetcher,
    )

    assert payload["ok"] is True
    assert payload["results"][0]["excerpt"] == "Provider snippet remains available."
    assert payload["results"][0]["fetch_status"] != "ok"
    assert payload["diagnostics"]["fetch_failed_count"] == 1


@pytest.mark.asyncio
async def test_research_search_treats_malformed_fetch_payload_as_fetch_failure() -> None:
    async def fetcher(url: str, max_chars: int) -> None:
        return None

    payload = await run_research_search(
        SearchOptions(query="q", fetch_top_k=1),
        provider_factory=lambda name: SnippetProvider(),
        fetcher=fetcher,
    )

    assert payload["ok"] is True
    assert payload["results"][0]["excerpt"] == "Provider snippet remains available."
    assert payload["results"][0]["fetch_status"] == "malformed_payload"
    assert payload["diagnostics"]["fetch_failed_count"] == 1


@pytest.mark.asyncio
async def test_research_search_falls_back_on_retryable_network_error() -> None:
    def provider_factory(name: str) -> NetworkFailProvider | FallbackProvider:
        if name == "tavily":
            return NetworkFailProvider()
        return FallbackProvider()

    payload = await run_research_search(
        SearchOptions(query="q", provider="tavily", fetch_top_k=0),
        provider_factory=provider_factory,
    )

    assert payload["ok"] is True
    assert payload["provider_attempts"] == [
        {"provider": "tavily", "status": "error", "error_kind": "network"},
        {"provider": "duckduckgo", "status": "success"},
    ]
    assert payload["diagnostics"]["fallback_from"] == "tavily"
    assert payload["results"][0]["provider"] == "duckduckgo"


@pytest.mark.asyncio
async def test_research_search_fetch_top_k_only_considers_top_ranked_slice() -> None:
    fetch_calls: list[str] = []

    async def fetcher(url: str, max_chars: int) -> dict[str, Any]:
        fetch_calls.append(url)
        return {
            "text": (
                '<external-content source="https://example.com">'
                "Fetched body text"
                "</external-content>"
            ),
            "extractor": "readability",
            "truncated": False,
            "status": 200,
        }

    payload = await run_research_search(
        SearchOptions(query="q", fetch_top_k=2),
        provider_factory=lambda name: UsefulTopResultsProvider(),
        fetcher=fetcher,
    )

    assert fetch_calls == []
    assert payload["results"][2]["rank"] == 3
    assert payload["results"][2]["fetched"] is False
    assert payload["diagnostics"]["fetched_count"] == 0


@pytest.mark.asyncio
async def test_research_search_filters_include_and_exclude_domains_before_fetch() -> None:
    fetch_calls: list[str] = []

    async def fetcher(url: str, max_chars: int) -> dict[str, Any]:
        fetch_calls.append(url)
        return {
            "text": (
                '<external-content source="https://example.com">'
                "Fetched body text"
                "</external-content>"
            ),
            "extractor": "readability",
            "truncated": False,
            "status": 200,
        }

    payload = await run_research_search(
        SearchOptions(
            query="python",
            include_domains=("https://PYTHON.org/docs",),
            exclude_domains=("docs.python.org",),
            fetch_top_k=5,
        ),
        provider_factory=lambda name: DomainFilteringProvider(),
        fetcher=fetcher,
    )

    assert payload["ok"] is True
    assert [result["title"] for result in payload["results"]] == [
        "Allowed exact",
        "Allowed subdomain",
    ]
    assert [result["rank"] for result in payload["results"]] == [1, 2]
    assert fetch_calls == [
        "https://python.org/about",
        "https://www.python.org/downloads",
    ]


@pytest.mark.asyncio
async def test_research_search_rejects_explicit_duckduckgo_recency_without_provider_call() -> None:
    def provider_factory(name: str) -> FakeProvider:
        raise AssertionError("provider_factory should not be called")

    payload = await run_research_search(
        SearchOptions(query="q", provider="duckduckgo", recency="week"),
        provider_factory=provider_factory,
    )

    assert payload["ok"] is False
    assert payload["error_kind"] == "invalid_request"
    assert payload["provider_attempts"] == []


@pytest.mark.asyncio
async def test_research_search_auto_recency_does_not_fallback_to_duckduckgo() -> None:
    attempted: list[str] = []

    def provider_factory(name: str) -> MissingKeyAuthProvider:
        attempted.append(name)
        return MissingKeyAuthProvider()

    payload = await run_research_search(
        SearchOptions(query="q", recency="week", fetch_top_k=0),
        provider_factory=provider_factory,
    )

    assert payload["ok"] is False
    assert attempted == ["tavily", "brave"]
    assert [attempt["provider"] for attempt in payload["provider_attempts"]] == [
        "tavily",
        "brave",
    ]


@pytest.mark.asyncio
async def test_research_search_passes_supported_recency_kwarg_only() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    payload = await run_research_search(
        SearchOptions(query="q", recency="week", fetch_top_k=0),
        provider_factory=lambda name: RecencyAwareProvider(calls),
    )

    assert payload["ok"] is True
    assert calls == [("q", {"max_results": 10, "recency": "week"})]


@pytest.mark.asyncio
async def test_research_search_rejects_empty_query_without_calling_provider() -> None:
    def provider_factory(name: str) -> FakeProvider:
        raise AssertionError("provider_factory should not be called")

    payload = await run_research_search(
        SearchOptions(query="   "),
        provider_factory=provider_factory,
    )

    assert payload["ok"] is False
    assert payload["error_kind"] == "invalid_request"
    assert payload["provider_attempts"] == []
