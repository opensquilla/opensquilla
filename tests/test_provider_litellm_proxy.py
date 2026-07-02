"""litellm_proxy provider: SquillaRouter stays the single routing authority.

LiteLLM is an optional gateway backend, never a semantic replacement: its
cross-model fallbacks are disabled per request, and its attribution headers
(which deployment actually served the call) are surfaced so a routing
deviation is never invisible.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from opensquilla.provider.compat_policy import compat_policy_for_kind
from opensquilla.provider.openai import OpenAIProvider
from opensquilla.provider.registry import get_provider_spec
from opensquilla.provider.selector import build_provider
from opensquilla.provider.types import ChatConfig, DoneEvent, Message


def test_litellm_proxy_registered_with_policy() -> None:
    spec = get_provider_spec("litellm_proxy")
    assert spec.backend == "openai_compat"
    assert spec.default_base_url == "http://localhost:4000/v1"
    assert spec.env_key == "LITELLM_API_KEY"
    policy = compat_policy_for_kind("litellm_proxy")
    assert policy.display_name == "LiteLLM Proxy"
    assert policy.sends_disable_fallbacks is True
    assert "x-litellm-model-id" in policy.attribution_response_headers
    # The proxy translates many upstreams; never synthesize text tool calls.
    assert policy.text_tool_synthesis is False


def test_build_provider_resolves_litellm_proxy() -> None:
    provider = build_provider("litellm_proxy", "gpt-5.4-nano", api_key="sk-x")
    assert isinstance(provider, OpenAIProvider)


def _sse_ok() -> bytes:
    chunks = [
        {"choices": [{"delta": {"content": "ok"}, "finish_reason": None}]},
        {
            "choices": [{"delta": {}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 2, "completion_tokens": 1},
        },
    ]
    body = b"".join(f"data: {json.dumps(chunk)}\n\n".encode() for chunk in chunks)
    return body + b"data: [DONE]\n\n"


def _run_capture(monkeypatch: Any, headers: dict[str, str]) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream", **headers},
            content=_sse_ok(),
        )

    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    def patched_async_client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr("opensquilla.provider.openai.httpx.AsyncClient", patched_async_client)

    provider = OpenAIProvider(
        api_key="sk-x",
        model="gpt-5.4-nano",
        base_url="http://localhost:4000/v1",
        provider_kind="litellm_proxy",
    )

    async def _run() -> list[Any]:
        return [
            ev
            async for ev in provider.chat([Message(role="user", content="hi")], config=ChatConfig())
        ]

    captured["events"] = asyncio.run(_run())
    return captured


def test_request_disables_gateway_fallbacks(monkeypatch: Any) -> None:
    captured = _run_capture(monkeypatch, headers={})
    assert captured["payload"]["disable_fallbacks"] is True
    # OpenRouter-only extras must not leak into the proxy request.
    assert "usage" not in captured["payload"]
    assert any(isinstance(e, DoneEvent) for e in captured["events"])


def test_attribution_headers_are_consumed_without_breaking_stream(monkeypatch: Any) -> None:
    captured = _run_capture(
        monkeypatch,
        headers={
            "x-litellm-model-id": "dep-123",
            "x-litellm-model-group": "gpt-5.4-nano",
            "x-litellm-attempted-fallbacks": "1",
        },
    )
    assert any(isinstance(e, DoneEvent) for e in captured["events"])


def test_other_kinds_do_not_send_disable_fallbacks(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_sse_ok(),
        )

    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    def patched_async_client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr("opensquilla.provider.openai.httpx.AsyncClient", patched_async_client)
    provider = OpenAIProvider(api_key="k", model="m", provider_kind="openai")

    async def _run() -> None:
        async for _ in provider.chat([Message(role="user", content="hi")], config=ChatConfig()):
            pass

    asyncio.run(_run())
    assert "disable_fallbacks" not in captured["payload"]
