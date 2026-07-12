"""Contract tests for the live LLM provider probe."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

from opensquilla.onboarding.probe import probe_llm_provider
from opensquilla.provider.failures import ProviderFailureKind
from opensquilla.provider.types import DoneEvent, ErrorEvent, TextDeltaEvent


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


def _patch_transport_error(monkeypatch: Any, exc: Exception) -> None:
    """Route provider HTTP through a transport that always fails to connect."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise exc

    transport = httpx.MockTransport(handler)
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
    # The probe never reached the network, so no round-trip time is reported.
    assert result.latency_ms == 0


def test_probe_rejects_unknown_provider_as_validation_error() -> None:
    with pytest.raises(ValueError, match="Unknown provider"):
        _probe(provider_id="no-such-provider", model="m")


def test_probe_requires_model() -> None:
    with pytest.raises(ValueError, match="Model is required"):
        _probe(provider_id="openai", model="", api_key="sk-test")


def test_probe_classifies_connection_failure_as_transport_transient(monkeypatch: Any) -> None:
    _patch_transport_error(monkeypatch, httpx.ConnectError("connection refused"))
    result = _probe(provider_id="openai", model="gpt-4o", api_key="sk-test")
    assert result.ok is False
    assert result.failure_kind == ProviderFailureKind.TRANSPORT_TRANSIENT.value


def test_probe_classifies_raised_stream_exception_as_transport_transient(
    monkeypatch: Any,
) -> None:
    """An exception escaping the adapter's stream hits the probe's own guard."""

    class _ExplodingProvider:
        provider_name = "openai"

        def chat(self, messages: Any, tools: Any = None, config: Any = None) -> Any:
            async def _gen() -> Any:
                raise RuntimeError("socket closed unexpectedly")
                yield  # pragma: no cover - makes _gen an async generator

            return _gen()

        async def list_models(self) -> list[Any]:
            return []

    monkeypatch.setattr(
        "opensquilla.onboarding.probe.build_provider",
        lambda *args, **kwargs: _ExplodingProvider(),
    )
    result = _probe(provider_id="openai", model="gpt-4o", api_key="sk-test")
    assert result.ok is False
    assert result.failure_kind == ProviderFailureKind.TRANSPORT_TRANSIENT.value
    assert "socket closed" in result.message


def test_probe_classifies_truncated_stream_as_malformed_response(monkeypatch: Any) -> None:
    """A stream that dies before its completion event is a malformed response."""

    class _TruncatedProvider:
        provider_name = "openai"

        def chat(self, messages: Any, tools: Any = None, config: Any = None) -> Any:
            async def _gen() -> Any:
                yield TextDeltaEvent(text="pa")  # then the stream just stops

            return _gen()

        async def list_models(self) -> list[Any]:
            return []

    monkeypatch.setattr(
        "opensquilla.onboarding.probe.build_provider",
        lambda *args, **kwargs: _TruncatedProvider(),
    )
    result = _probe(provider_id="openai", model="gpt-4o", api_key="sk-test")
    assert result.ok is False
    assert result.failure_kind == ProviderFailureKind.MALFORMED_RESPONSE.value
    assert "without a completion event" in result.message


def test_probe_redacts_key_material_echoed_by_auth_errors(monkeypatch: Any) -> None:
    """Provider 401 bodies can echo the bad key; the probe must never repeat it."""
    leaked = "sk-verysecretsynthetictoken123"
    _patch_response(
        monkeypatch,
        httpx.Response(
            401,
            headers={"content-type": "application/json"},
            content=json.dumps(
                {"error": {"message": f"Incorrect API key provided: {leaked}"}}
            ).encode(),
        ),
    )
    result = _probe(provider_id="openai", model="gpt-4o", api_key="sk-bad")
    assert result.ok is False
    assert result.failure_kind == ProviderFailureKind.AUTH_INVALID.value
    assert leaked not in result.message
    assert "***" in result.message


def _delayed_provider(events: list[Any], delay_s: float = 0.02) -> Any:
    """Fake provider whose stream sleeps once, so latency is provably > 0.

    The reported integer can be slightly shorter than the requested sleep on
    event loops with coarse timer resolution, so callers only rely on it being
    positive.
    """

    class _DelayedProvider:
        provider_name = "openai"

        def chat(self, messages: Any, tools: Any = None, config: Any = None) -> Any:
            async def _gen() -> Any:
                await asyncio.sleep(delay_s)
                for event in events:
                    yield event

            return _gen()

        async def list_models(self) -> list[Any]:
            return []

    return _DelayedProvider()


def test_probe_reports_latency_on_ok_path(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "opensquilla.onboarding.probe.build_provider",
        lambda *args, **kwargs: _delayed_provider([DoneEvent()], delay_s=0.02),
    )
    result = _probe(provider_id="openai", model="gpt-4o", api_key="sk-test")
    assert result.ok is True
    assert isinstance(result.latency_ms, int)
    assert result.latency_ms > 0


def test_probe_reports_latency_on_classified_error_path(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "opensquilla.onboarding.probe.build_provider",
        lambda *args, **kwargs: _delayed_provider(
            [ErrorEvent(message="Incorrect API key provided", code="401")], delay_s=0.02
        ),
    )
    result = _probe(provider_id="openai", model="gpt-4o", api_key="sk-bad")
    assert result.ok is False
    assert result.failure_kind == ProviderFailureKind.AUTH_INVALID.value
    assert isinstance(result.latency_ms, int)
    assert result.latency_ms > 0
