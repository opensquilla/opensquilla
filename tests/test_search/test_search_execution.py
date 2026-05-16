from __future__ import annotations

import pytest

from opensquilla.search.execution import run_search_payload, search_runtime_status
from opensquilla.search.registry import register_provider
from opensquilla.search.types import SearchProviderError, SearchProviderSpec, SearchResult
from opensquilla.tools.builtin.web import configure_search, run_web_search_payload


class OkSearchProvider:
    name = "execution_ok"

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        return [SearchResult(title="Title", url="https://example.com", snippet=query)]


class FailingSearchProvider:
    name = "execution_fail"

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        raise SearchProviderError(
            provider=self.name,
            kind="network",
            message="network down",
            retryable=True,
        )


@pytest.fixture(autouse=True)
def _reset_search_runtime() -> None:
    configure_search("duckduckgo", max_results=5)
    yield
    configure_search("duckduckgo", max_results=5)


@pytest.mark.asyncio
async def test_search_execution_returns_status_and_query_payload() -> None:
    register_provider(
        "execution_ok",
        OkSearchProvider,
        SearchProviderSpec(provider_id="execution_ok"),
    )
    configure_search("execution_ok", max_results=4, diagnostics=True)

    status = search_runtime_status()
    payload = await run_search_payload("hello", 2)

    assert status["provider"] == "execution_ok"
    assert status["configured"] is True
    assert payload["ok"] is True
    assert payload["results"][0]["snippet"] == "hello"
    assert "attempts" not in payload


@pytest.mark.asyncio
async def test_search_execution_preserves_failure_and_sensitive_payload_shape() -> None:
    register_provider(
        "execution_fail",
        FailingSearchProvider,
        SearchProviderSpec(provider_id="execution_fail"),
    )
    configure_search("execution_fail", diagnostics=True)

    failed = await run_search_payload("hello")
    sensitive = await run_search_payload("API_KEY=super-secret-value")

    assert failed["ok"] is False
    assert failed["error"]["kind"] == "network"
    assert failed["error"]["retryable"] is True
    assert sensitive["query"] == "[redacted]"
    assert "super-secret-value" not in repr(sensitive)
    assert sensitive["error"]["kind"] == "invalid_request"


@pytest.mark.asyncio
async def test_web_search_payload_is_a_compatibility_wrapper() -> None:
    register_provider(
        "execution_ok",
        OkSearchProvider,
        SearchProviderSpec(provider_id="execution_ok"),
    )
    configure_search("execution_ok", max_results=4)

    assert await run_web_search_payload("hello", 2) == await run_search_payload("hello", 2)
