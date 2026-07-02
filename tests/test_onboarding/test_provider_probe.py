"""Contract tests for the live LLM provider probe."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

from opensquilla.onboarding.probe import probe_llm_provider
from opensquilla.provider.failures import ProviderFailureKind


def _sse_ok_body() -> bytes:
    chunks = [
        {"choices": [{"delta": {"content": "pong"}, "finish_reason": None}]},
        {
            "choices": [{"delta": {}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        },
    ]
    body = b"".join(f"data: {json.dumps(chunk)}\n\n".encode() for chunk in chunks)
    return body + b"data: [DONE]\n\n"


def _patch_response(monkeypatch: Any, response: httpx.Response) -> None:
    transport = httpx.MockTransport(lambda request: response)
    real_async_client = httpx.AsyncClient

    def patched_async_client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr("opensquilla.provider.openai.httpx.AsyncClient", patched_async_client)


def _probe(**kwargs: Any):
    return asyncio.run(probe_llm_provider(**kwargs))


def test_probe_reports_ok_on_completed_turn(monkeypatch: Any) -> None:
    _patch_response(
        monkeypatch,
        httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_sse_ok_body(),
        ),
    )
    result = _probe(provider_id="openai", model="gpt-4o", api_key="sk-test")
    assert result.ok is True
    assert result.failure_kind == ""


def test_probe_classifies_bad_key_as_auth_invalid(monkeypatch: Any) -> None:
    _patch_response(
        monkeypatch,
        httpx.Response(
            401,
            headers={"content-type": "application/json"},
            content=b'{"error": {"message": "Incorrect API key provided"}}',
        ),
    )
    result = _probe(provider_id="openai", model="gpt-4o", api_key="sk-bad")
    assert result.ok is False
    assert result.failure_kind == ProviderFailureKind.AUTH_INVALID.value
    assert result.code == "401"
    assert "Incorrect API key" in result.message


def test_probe_classifies_unknown_model_as_model_not_found(monkeypatch: Any) -> None:
    _patch_response(
        monkeypatch,
        httpx.Response(
            404,
            headers={"content-type": "application/json"},
            content=b'{"error": {"message": "The model does not exist"}}',
        ),
    )
    result = _probe(provider_id="openai", model="gpt-nope", api_key="sk-test")
    assert result.ok is False
    assert result.failure_kind == ProviderFailureKind.MODEL_NOT_FOUND.value


def test_probe_reports_missing_key_without_network(monkeypatch: Any) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    result = _probe(provider_id="openai", model="gpt-4o")
    assert result.ok is False
    assert result.failure_kind == ProviderFailureKind.AUTH_INVALID.value
    assert "OPENAI_API_KEY" in result.message


def test_probe_rejects_unknown_provider_as_validation_error() -> None:
    with pytest.raises(ValueError, match="Unknown provider"):
        _probe(provider_id="no-such-provider", model="m")


def test_probe_requires_model() -> None:
    with pytest.raises(ValueError, match="Model is required"):
        _probe(provider_id="openai", model="", api_key="sk-test")
