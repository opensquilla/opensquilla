"""Provider error sinks never expose the concrete active API key."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

import opensquilla.provider.anthropic as anthropic_module
import opensquilla.provider.ollama as ollama_module
import opensquilla.provider.openai as openai_module
import opensquilla.provider.openai_responses as responses_module
from opensquilla.provider.anthropic import AnthropicProvider
from opensquilla.provider.failures import ProviderFailureKind, classify_provider_error
from opensquilla.provider.ollama import OllamaProvider
from opensquilla.provider.openai import OpenAIProvider
from opensquilla.provider.openai_responses import OpenAIResponsesProvider
from opensquilla.provider.types import ChatConfig, ErrorEvent, Message

# Deliberately too short for shape-based long-token redaction.  Exact
# provider-boundary replacement must protect it solely because it is the active
# credential; the prefix also exercises Google-style API key shapes.
_API_KEY = "AIza"


def test_tiny_synthetic_key_does_not_corrupt_unrelated_error_words() -> None:
    from opensquilla.provider.error_redaction import redact_upstream_error_text

    assert (
        redact_upstream_error_text("document block malformed", api_key="k")
        == "document block malformed"
    )


class _CapturedLog:
    def __init__(self) -> None:
        self.records: list[tuple[str, str, tuple[Any, ...], dict[str, Any]]] = []

    def __getattr__(self, level: str) -> Any:
        def record(event: str, *args: Any, **kwargs: Any) -> None:
            self.records.append((level, event, args, kwargs))

        return record


def _patch_transport(
    monkeypatch: pytest.MonkeyPatch,
    handler: Any,
) -> None:
    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    def patched_async_client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", patched_async_client)


def _provider_case(kind: str) -> tuple[Any, Any, str]:
    if kind == "openai":
        return (
            OpenAIProvider(api_key=_API_KEY, model="synthetic-chat"),
            openai_module,
            "openai",
        )
    if kind == "openai_responses":
        return (
            OpenAIResponsesProvider(api_key=_API_KEY, model="synthetic-responses"),
            responses_module,
            "openai_responses",
        )
    if kind == "ollama":
        return (
            OllamaProvider(api_key=_API_KEY, model="synthetic-ollama"),
            ollama_module,
            "ollama",
        )
    return (
        AnthropicProvider(api_key=_API_KEY, model="synthetic-anthropic"),
        anthropic_module,
        "anthropic",
    )


async def _events(provider: Any) -> list[Any]:
    return [
        event
        async for event in provider.chat(
            [Message(role="user", content="synthetic prompt")],
            config=ChatConfig(max_tokens=1),
        )
    ]


@pytest.mark.parametrize("kind", ["openai", "openai_responses", "anthropic", "ollama"])
async def test_http_error_echoed_key_is_redacted_from_event_trace_and_log(
    kind: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    trace_path = tmp_path / f"{kind}.jsonl"
    monkeypatch.setenv("OPENSQUILLA_LLM_TRACE_RECORDER", "full")
    monkeypatch.setenv("OPENSQUILLA_LLM_TRACE_PATH", str(trace_path))
    captured_log = _CapturedLog()
    provider, module, failure_provider = _provider_case(kind)
    monkeypatch.setattr(module, "log", captured_log)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            request=request,
            json={"error": {"message": f"invalid api key {_API_KEY}"}},
        )

    _patch_transport(monkeypatch, handler)
    events = await _events(provider)

    errors = [event for event in events if isinstance(event, ErrorEvent)]
    assert len(errors) == 1
    error = errors[0]
    assert error.code == "401"
    assert _API_KEY not in error.message
    assert classify_provider_error(
        failure_provider,
        401,
        error.code,
        error.message,
    ) is ProviderFailureKind.AUTH_INVALID

    trace_text = trace_path.read_text(encoding="utf-8")
    assert _API_KEY not in trace_text
    trace_rows = [json.loads(line) for line in trace_text.splitlines()]
    error_rows = [row for row in trace_rows if row["event"] == "llm.error"]
    assert len(error_rows) == 1
    assert error_rows[0]["status_code"] == 401
    assert error_rows[0]["code"] == "401"
    assert _API_KEY not in repr(captured_log.records)
    if kind == "openai":
        assert any(event == "provider.chat_http_error" for _, event, _, _ in captured_log.records)


@pytest.mark.parametrize("kind", ["openai", "openai_responses", "anthropic", "ollama"])
async def test_transport_error_echoed_key_is_redacted_from_event_and_trace(
    kind: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    trace_path = tmp_path / f"{kind}-transport.jsonl"
    monkeypatch.setenv("OPENSQUILLA_LLM_TRACE_RECORDER", "full")
    monkeypatch.setenv("OPENSQUILLA_LLM_TRACE_PATH", str(trace_path))
    provider, _, failure_provider = _provider_case(kind)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(
            f"synthetic transport echoed {_API_KEY}",
            request=request,
        )

    _patch_transport(monkeypatch, handler)
    events = await _events(provider)

    errors = [event for event in events if isinstance(event, ErrorEvent)]
    assert len(errors) == 1
    error = errors[0]
    assert error.code == "request_error"
    assert _API_KEY not in error.message
    assert classify_provider_error(
        failure_provider,
        None,
        error.code,
        error.message,
    ) is ProviderFailureKind.TRANSPORT_TRANSIENT
    assert _API_KEY not in trace_path.read_text(encoding="utf-8")


async def test_ollama_timeout_error_echoed_key_is_redacted_from_event_and_trace(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    trace_path = tmp_path / "ollama-timeout.jsonl"
    monkeypatch.setenv("OPENSQUILLA_LLM_TRACE_RECORDER", "full")
    monkeypatch.setenv("OPENSQUILLA_LLM_TRACE_PATH", str(trace_path))
    provider, _, _ = _provider_case("ollama")

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout(
            f"synthetic timeout echoed {_API_KEY}",
            request=request,
        )

    _patch_transport(monkeypatch, handler)
    events = await _events(provider)

    errors = [event for event in events if isinstance(event, ErrorEvent)]
    assert len(errors) == 1
    assert errors[0].code == "timeout"
    assert _API_KEY not in errors[0].message
    assert _API_KEY not in trace_path.read_text(encoding="utf-8")


@pytest.mark.parametrize("kind", ["openai", "openai_responses", "anthropic", "ollama"])
async def test_success_status_error_frame_echoed_key_is_redacted_from_all_sinks(
    kind: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    trace_path = tmp_path / f"{kind}-error-frame.jsonl"
    monkeypatch.setenv("OPENSQUILLA_LLM_TRACE_RECORDER", "full")
    monkeypatch.setenv("OPENSQUILLA_LLM_TRACE_PATH", str(trace_path))
    provider, module, failure_provider = _provider_case(kind)
    captured_log = _CapturedLog()
    monkeypatch.setattr(module, "log", captured_log)
    raw_code = "authentication_error" if kind == "anthropic" else "auth_error"
    if kind == "ollama":
        raw_code = f"{raw_code}-{_API_KEY}"
    expected_code = raw_code.replace(_API_KEY, "***")
    raw_message = (
        f"unauthorized api key {_API_KEY}"
        if kind == "ollama"
        else f"invalid api key {_API_KEY}"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if kind == "openai":
            content = "data: " + json.dumps(
                {
                    "error": {
                        "code": expected_code,
                        "message": raw_message,
                    }
                }
            ) + "\n\n"
            return httpx.Response(200, request=request, text=content)
        if kind == "anthropic":
            content = "data: " + json.dumps(
                {
                    "type": "error",
                    "error": {
                        "type": raw_code,
                        "message": raw_message,
                    },
                }
            ) + "\n\n"
            return httpx.Response(200, request=request, text=content)
        if kind == "ollama":
            content = json.dumps(
                {
                    "error": {
                        "code": raw_code,
                        "message": raw_message,
                    }
                }
            ) + "\n"
            return httpx.Response(200, request=request, text=content)
        return httpx.Response(
            200,
            request=request,
            json={
                "id": "synthetic-response",
                "status": "failed",
                "error": {
                    "code": raw_code,
                    "message": raw_message,
                },
                "output": [],
                "usage": {},
            },
        )

    _patch_transport(monkeypatch, handler)
    events = await _events(provider)

    errors = [event for event in events if isinstance(event, ErrorEvent)]
    assert len(errors) == 1
    error = errors[0]
    assert error.code == expected_code
    assert _API_KEY not in error.message
    assert classify_provider_error(
        failure_provider,
        None,
        error.code,
        error.message,
    ) is ProviderFailureKind.AUTH_INVALID
    assert _API_KEY not in trace_path.read_text(encoding="utf-8")
    assert _API_KEY not in repr(captured_log.records)


class _ExplodingStream(httpx.AsyncByteStream):
    async def __aiter__(self) -> Any:
        raise ValueError(f"synthetic stream handler echoed {_API_KEY}")
        yield b""  # pragma: no cover - makes this an async generator


@pytest.mark.parametrize("kind", ["openai", "anthropic", "ollama"])
async def test_stream_internal_exception_is_redacted_before_trace_event_and_log(
    kind: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    trace_path = tmp_path / f"{kind}-internal.jsonl"
    monkeypatch.setenv("OPENSQUILLA_LLM_TRACE_RECORDER", "full")
    monkeypatch.setenv("OPENSQUILLA_LLM_TRACE_PATH", str(trace_path))
    provider, module, _ = _provider_case(kind)
    captured_log = _CapturedLog()
    monkeypatch.setattr(module, "log", captured_log)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, request=request, stream=_ExplodingStream())

    _patch_transport(monkeypatch, handler)
    events = await _events(provider)

    errors = [event for event in events if isinstance(event, ErrorEvent)]
    assert len(errors) == 1
    assert errors[0].code == "provider_internal"
    assert _API_KEY not in errors[0].message
    assert _API_KEY not in trace_path.read_text(encoding="utf-8")
    assert captured_log.records
    assert _API_KEY not in repr(captured_log.records)
    assert all(level != "exception" for level, _, _, _ in captured_log.records)


@pytest.mark.parametrize("kind", ["openai", "openai_responses", "ollama"])
async def test_model_discovery_transport_error_preserves_type_but_redacts_key(
    kind: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider, _, _ = _provider_case(kind)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(
            f"discovery transport echoed {_API_KEY}",
            request=request,
        )

    _patch_transport(monkeypatch, handler)
    with pytest.raises(httpx.ConnectError) as raised:
        await provider.list_models(raise_on_error=True)

    assert _API_KEY not in str(raised.value)
    assert "discovery transport echoed" in str(raised.value)
