from __future__ import annotations

import json

import httpx
import pytest

from opensquilla.rag_provider.client import RagProviderClient
from opensquilla.rag_provider.protocol import (
    ProviderAuthenticationError,
    ProviderNotFound,
    ProviderProtocolViolation,
    ProviderUnavailable,
)

from .test_protocol import capabilities, result


@pytest.mark.asyncio
async def test_client_sends_bearer_and_standard_search_request(monkeypatch) -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/capabilities"):
            return httpx.Response(200, json=capabilities())
        return httpx.Response(
            200,
            json={
                "returnedCount": 1,
                "totalMatched": None,
                "resultsTruncated": False,
                "results": [result(1)],
            },
        )

    monkeypatch.setenv("RAG_TOKEN", "secret")
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = RagProviderClient(
        base_url="https://knowledge.example.com/opensquilla-rag",
        token_env="RAG_TOKEN",
        connect_timeout_seconds=2,
        request_timeout_seconds=5,
        http_client=http,
    )
    snapshot = await client.capabilities()
    await client.search(
        query="NAND",
        limit=8,
        budget=snapshot.effective_search_budget,
        collection_ids=("datasets",),
        retrieval_profile="lexical",
    )

    assert requests[0].headers["authorization"] == "Bearer secret"
    body = json.loads(requests[1].content)
    assert body == {
        "query": "NAND",
        "limit": 8,
        "budget": {"maxSnippetChars": 800, "maxTotalChars": 12000},
        "scope": {"collectionIds": ["datasets"]},
        "retrievalProfile": "lexical",
    }
    await http.aclose()


@pytest.mark.asyncio
async def test_client_rejects_oversized_response_before_json_parse() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/json", "content-length": "70000"},
            content=b"{}",
        )

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = RagProviderClient(
        base_url="https://knowledge.example.com/opensquilla-rag",
        token_env=None,
        connect_timeout_seconds=2,
        request_timeout_seconds=5,
        http_client=http,
    )
    with pytest.raises(Exception, match="response body exceeds"):
        await client.capabilities()
    await http.aclose()


@pytest.mark.parametrize(
    "base_url",
    [
        "ftp://knowledge.example.com/provider",
        "https://user:password@knowledge.example.com/provider",
        "https://knowledge.example.com/provider?token=secret",
        "https://knowledge.example.com/provider#fragment",
    ],
)
def test_client_rejects_unsafe_base_urls(base_url: str) -> None:
    with pytest.raises(ValueError):
        RagProviderClient(
            base_url=base_url,
            token_env=None,
            connect_timeout_seconds=2,
            request_timeout_seconds=5,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "error_type"),
    [
        (401, ProviderAuthenticationError),
        (403, ProviderAuthenticationError),
        (404, ProviderNotFound),
        (429, ProviderUnavailable),
        (503, ProviderUnavailable),
    ],
)
async def test_client_maps_http_status_to_safe_error(
    status: int,
    error_type: type[Exception],
) -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=b"secret upstream response body")

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = RagProviderClient(
        base_url="https://knowledge.example.com/provider",
        token_env=None,
        connect_timeout_seconds=2,
        request_timeout_seconds=5,
        http_client=http,
    )

    with pytest.raises(error_type) as caught:
        await client.capabilities()

    assert "secret" not in str(caught.value)
    await http.aclose()


@pytest.mark.asyncio
async def test_invalid_content_length_is_a_protocol_violation() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/json", "content-length": "not-an-int"},
            content=b"{}",
        )

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = RagProviderClient(
        base_url="https://knowledge.example.com/provider",
        token_env=None,
        connect_timeout_seconds=2,
        request_timeout_seconds=5,
        http_client=http,
    )

    with pytest.raises(ProviderProtocolViolation):
        await client.capabilities()
    await http.aclose()
