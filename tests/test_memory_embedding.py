from __future__ import annotations

import pytest

from opensquilla.memory.embedding import LocalEmbeddingProvider, OpenAIEmbeddingProvider


class _FakeEmbeddingResponse:
    def __init__(self, data: dict) -> None:
        self._data = data

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._data


class _FakeEmbeddingClient:
    def __init__(self, captured: dict[str, object]) -> None:
        self._captured = captured

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    async def post(self, url, *, headers, json, timeout):
        self._captured["url"] = url
        self._captured["headers"] = headers
        self._captured["json"] = json
        self._captured["timeout"] = timeout
        inputs = json["input"] if isinstance(json["input"], list) else [json["input"]]
        return _FakeEmbeddingResponse(
            {
                "data": [
                    {"index": index, "embedding": [float(index), 1.0]}
                    for index, _ in enumerate(inputs)
                ]
            }
        )


def _patch_embedding_client(monkeypatch, captured: dict[str, object]) -> None:
    monkeypatch.setattr(
        "opensquilla.memory.embedding.httpx.AsyncClient",
        lambda **kwargs: _FakeEmbeddingClient(captured),
    )


def test_local_embedding_tokenizes_for_onnx_inputs() -> None:
    pytest.importorskip("numpy", reason="local ONNX embedding tokenization needs numpy")

    class _Encoding:
        ids = [101, 102]
        attention_mask = [1, 1]
        type_ids = [0, 0]

    class _Tokenizer:
        def encode_batch(self, texts):
            assert texts == ["hello"]
            return [_Encoding()]

    provider = LocalEmbeddingProvider()
    provider._onnx_tokenizer = _Tokenizer()

    feed = provider._tokenize_onnx(["hello"], ["input_ids", "attention_mask"])

    assert sorted(feed) == ["attention_mask", "input_ids"]
    assert feed["input_ids"].tolist() == [[101, 102]]
    assert feed["attention_mask"].tolist() == [[1, 1]]


@pytest.mark.asyncio
async def test_openai_embedding_provider_adds_openrouter_app_attribution_for_query(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}
    _patch_embedding_client(monkeypatch, captured)
    provider = OpenAIEmbeddingProvider(
        api_key="or-test",
        base_url="https://openrouter.ai/api/v1",
        model="openai/text-embedding-3-small",
    )

    embedding = await provider.embed_query("memory query")

    assert embedding == [0.0, 1.0]
    assert captured["url"] == "https://openrouter.ai/api/v1/embeddings"
    assert captured["headers"] == {
        "Authorization": "Bearer or-test",
        "HTTP-Referer": "https://opensquilla.ai",
        "X-OpenRouter-Title": "OpenSquilla",
        "X-OpenRouter-Categories": "cli-agent,personal-agent",
    }


@pytest.mark.asyncio
async def test_openai_embedding_provider_skips_app_attribution_for_non_openrouter(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}
    _patch_embedding_client(monkeypatch, captured)
    provider = OpenAIEmbeddingProvider(
        api_key="openai-test",
        base_url="https://api.openai.com/v1",
        model="text-embedding-3-small",
    )

    embeddings = await provider.embed_batch(["first", "second"])

    assert embeddings == [[0.0, 1.0], [1.0, 1.0]]
    assert captured["url"] == "https://api.openai.com/v1/embeddings"
    assert captured["headers"] == {"Authorization": "Bearer openai-test"}


@pytest.mark.asyncio
async def test_openai_embedding_provider_sends_dimensions_when_configured(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}
    _patch_embedding_client(monkeypatch, captured)
    provider = OpenAIEmbeddingProvider(
        api_key="openai-test",
        base_url="https://api.openai.com/v1",
        model="text-embedding-3-small",
        dimensions=512,
    )

    await provider.embed_query("memory query")

    assert captured["json"] == {
        "input": "memory query",
        "model": "text-embedding-3-small",
        "dimensions": 512,
    }
