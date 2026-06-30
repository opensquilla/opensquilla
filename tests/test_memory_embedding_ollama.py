from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from opensquilla.memory.embedding import OllamaEmbeddingProvider


def _patch(monkeypatch: Any, captured: dict[str, Any], embeddings: list[list[float]]) -> None:
    captured["calls"] = 0

    def handler(request: httpx.Request) -> httpx.Response:
        captured["calls"] += 1
        captured["url"] = str(request.url)
        captured["payload"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json={"model": "nomic-embed-text", "embeddings": embeddings})

    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    def patched_async_client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr("opensquilla.memory.embedding.httpx.AsyncClient", patched_async_client)


def test_embed_query_uses_api_embed_endpoint(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}
    _patch(monkeypatch, captured, [[0.1, 0.2, 0.3]])
    provider = OllamaEmbeddingProvider(model="nomic-embed-text")

    vec = asyncio.run(provider.embed_query("hello"))

    assert captured["url"] == "http://localhost:11434/api/embed"
    assert captured["payload"] == {"model": "nomic-embed-text", "input": ["hello"]}
    assert vec == [0.1, 0.2, 0.3]


def test_embed_batch_sends_single_request_with_all_inputs(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}
    _patch(monkeypatch, captured, [[1.0], [2.0], [3.0]])
    provider = OllamaEmbeddingProvider(model="nomic-embed-text")

    vectors = asyncio.run(provider.embed_batch(["a", "b", "c"]))

    # One round trip for the whole batch, not one per text.
    assert captured["calls"] == 1
    assert captured["payload"]["input"] == ["a", "b", "c"]
    assert vectors == [[1.0], [2.0], [3.0]]


def test_embed_batch_empty_makes_no_request(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}
    _patch(monkeypatch, captured, [])
    provider = OllamaEmbeddingProvider(model="nomic-embed-text")

    vectors = asyncio.run(provider.embed_batch([]))

    assert vectors == []
    assert captured["calls"] == 0
