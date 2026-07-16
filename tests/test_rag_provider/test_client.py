from __future__ import annotations

import json

import httpx
import pytest

from opensquilla.rag_provider.client import RagProviderClient
from opensquilla.rag_provider.protocol import (
    ProviderAuthenticationError,
    ProviderIncompatible,
    ProviderNotFound,
    ProviderProtocolViolation,
    ProviderUnavailable,
    SearchBudget,
)

from .test_protocol import capabilities, result, result_v11, search_v11


async def _validated_v11_search(*, requested_profile: str):
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/capabilities"):
            return httpx.Response(200, json=capabilities(version="1.1"))
        return httpx.Response(200, json=search_v11([result_v11(1)]))

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = RagProviderClient(
        base_url="https://knowledge.example.com/provider",
        token_env=None,
        connect_timeout_seconds=2,
        request_timeout_seconds=5,
        http_client=http,
    )
    snapshot = await client.capabilities()
    validated = await client.search(
        query="NAND",
        limit=8,
        budget=snapshot.effective_search_budget,
        retrieval_profile=requested_profile,
        protocol_version=snapshot.protocol_version,
    )
    await http.aclose()
    return validated


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
        protocol_version=snapshot.protocol_version,
    )

    assert requests[0].headers["authorization"] == "Bearer secret"
    body = json.loads(requests[1].content)
    assert body == {
        "query": "NAND",
        "limit": 8,
        "budget": {
            "maxSnippetChars": 800,
            "maxTotalChars": 12000,
            "maxChunkChars": 8000,
        },
        "scope": {"collectionIds": ["datasets"]},
        "retrievalProfile": "lexical",
    }
    await http.aclose()


@pytest.mark.asyncio
async def test_client_validates_search_with_exact_snapshot_protocol_version() -> None:
    validated = await _validated_v11_search(requested_profile="vector")

    assert validated.payload["results"][0]["chunk"] == {
        "id": "chunk_1",
        "content": "complete evidence",
        "contentChars": 17,
    }


@pytest.mark.asyncio
async def test_client_preserves_provider_returned_retrieval_profile() -> None:
    validated = await _validated_v11_search(requested_profile="vector")

    assert validated.payload["retrieval"]["profile"] == "hybrid"


@pytest.mark.asyncio
async def test_client_validates_get_with_exact_snapshot_protocol_version() -> None:
    search_result = result_v11(1)

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/capabilities"):
            return httpx.Response(200, json=capabilities(version="1.1"))
        return httpx.Response(
            200,
            json={
                "evidenceId": search_result["evidenceId"],
                "document": search_result["document"],
                "content": search_result["chunk"]["content"],
                "contentChars": search_result["chunk"]["contentChars"],
                "previousCursor": None,
                "nextCursor": None,
                "citation": search_result["citation"],
            },
        )

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = RagProviderClient(
        base_url="https://knowledge.example.com/provider",
        token_env=None,
        connect_timeout_seconds=2,
        request_timeout_seconds=5,
        http_client=http,
    )
    snapshot = await client.capabilities()

    validated = await client.get(
        evidence_id="ev_1",
        cursor=None,
        max_content_chars=snapshot.limits.max_get_content_chars,
        protocol_version=snapshot.protocol_version,
    )

    assert validated["document"]["id"] == "doc_1"
    assert validated["contentChars"] == 17
    await http.aclose()


@pytest.mark.asyncio
async def test_client_does_not_infer_future_compatible_protocol_version() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=search_v11([result_v11(1)]))

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = RagProviderClient(
        base_url="https://knowledge.example.com/provider",
        token_env=None,
        connect_timeout_seconds=2,
        request_timeout_seconds=5,
        http_client=http,
    )

    with pytest.raises(ProviderIncompatible):
        await client.search(
            query="NAND",
            limit=8,
            budget=SearchBudget(800, 12_000, max_chunk_chars=8_000),
            protocol_version="1.2",
        )
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
