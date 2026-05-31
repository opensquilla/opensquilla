import asyncio
import json

import httpx
import pytest

from opensquilla.provider.anthropic import (
    AnthropicProvider,
    _anthropic_input_token_counts,
    _anthropic_iteration_token_counts,
    _build_message_payload,
)
from opensquilla.provider.types import (
    ChatConfig,
    ContentBlockCompaction,
    DoneEvent,
    ErrorEvent,
    Message,
)


def test_anthropic_input_tokens_include_cache_read_and_creation_tokens() -> None:
    total, cache_read, cache_creation = _anthropic_input_token_counts(
        {
            "input_tokens": 21,
            "cache_read_input_tokens": 188_086,
            "cache_creation_input_tokens": 456,
            "output_tokens": 393,
        }
    )

    assert total == 188_563
    assert cache_read == 188_086
    assert cache_creation == 456


def test_anthropic_input_tokens_include_structured_cache_creation_tokens() -> None:
    total, cache_read, cache_creation = _anthropic_input_token_counts(
        {
            "input_tokens": 21,
            "cache_read_input_tokens": 100,
            "cache_creation": {
                "ephemeral_5m_input_tokens": 456,
                "ephemeral_1h_input_tokens": 100,
            },
            "output_tokens": 393,
        }
    )

    assert total == 677
    assert cache_read == 100
    assert cache_creation == 556


def test_anthropic_iteration_tokens_sum_compaction_and_message_usage() -> None:
    input_tokens, output_tokens = _anthropic_iteration_token_counts(
        {
            "input_tokens": 23000,
            "output_tokens": 1000,
            "iterations": [
                {"type": "compaction", "input_tokens": 180000, "output_tokens": 3500},
                {"type": "message", "input_tokens": 23000, "output_tokens": 1000},
            ],
        }
    )

    assert input_tokens == 203000
    assert output_tokens == 4500


def test_anthropic_message_payload_replays_compaction_block_with_cache_control() -> None:
    payload = _build_message_payload(
        Message(
            role="assistant",
            content=[
                ContentBlockCompaction(
                    content="summary text",
                    cache_control={"type": "ephemeral"},
                )
            ],
        )
    )

    assert payload == {
        "role": "assistant",
        "content": [
            {
                "type": "compaction",
                "content": "summary text",
                "cache_control": {"type": "ephemeral"},
            }
        ],
    }


def _sse_body(events: list[dict]) -> bytes:
    parts = []
    for ev in events:
        parts.append(f"event: {ev['type']}\n".encode())
        parts.append(f"data: {json.dumps(ev)}\n\n".encode())
    return b"".join(parts)


@pytest.mark.parametrize(
    "base_url",
    [
        "https://api.minimaxi.com/anthropic",
        "https://api.minimax.io/anthropic",
    ],
)
def test_minimax_anthropic_endpoints_use_authorization_bearer(
    monkeypatch,
    base_url: str,
) -> None:
    captured: dict[str, object] = {}
    body = _sse_body(
        [
            {
                "type": "message_start",
                "message": {"id": "msg_1", "model": "MiniMax-M2.7", "usage": {}},
            },
            {"type": "message_stop"},
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = request.headers
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=body,
        )

    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    def patched_async_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr("opensquilla.provider.anthropic.httpx.AsyncClient", patched_async_client)

    provider = AnthropicProvider(
        api_key="test-key",
        model="MiniMax-M2.7",
        base_url=base_url,
    )

    async def _collect() -> None:
        async for _ in provider.chat([Message(role="user", content="hi")], config=ChatConfig()):
            pass

    asyncio.run(_collect())

    headers = captured["headers"]
    assert captured["url"] == f"{base_url}/v1/messages"
    assert headers["Authorization"] == "Bearer test-key"
    assert "x-api-key" not in headers


def test_anthropic_done_event_carries_cache_write_tokens(monkeypatch) -> None:
    """End-to-end: SSE usage populates DoneEvent.cache_write_tokens."""

    sse_events = [
        {
            "type": "message_start",
            "message": {
                "id": "msg_1",
                "model": "claude-opus-4-7",
                "usage": {
                    "input_tokens": 10,
                    "cache_read_input_tokens": 1000,
                    "cache_creation_input_tokens": 500,
                },
            },
        },
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "text", "text": ""},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": "ok"},
        },
        {"type": "content_block_stop", "index": 0},
        {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn"},
            "usage": {
                "output_tokens": 5,
                "cache_read_input_tokens": 1000,
                "cache_creation_input_tokens": 500,
            },
        },
        {"type": "message_stop"},
    ]

    body = _sse_body(sse_events)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=body,
        )

    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    def patched_async_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr("opensquilla.provider.anthropic.httpx.AsyncClient", patched_async_client)

    provider = AnthropicProvider(api_key="test", model="claude-opus-4-7")

    async def _collect() -> DoneEvent:
        done: DoneEvent | None = None
        async for ev in provider.chat([Message(role="user", content="hi")], config=ChatConfig()):
            if isinstance(ev, DoneEvent):
                done = ev
        assert done is not None
        return done

    done = asyncio.run(_collect())
    assert done.cached_tokens == 1000
    assert done.cache_write_tokens == 500


def test_anthropic_done_event_includes_compaction_iteration_usage(monkeypatch) -> None:
    sse_events = [
        {
            "type": "message_start",
            "message": {
                "id": "msg_1",
                "model": "claude-opus-4-7",
                "usage": {"input_tokens": 10},
            },
        },
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_stop", "index": 0},
        {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn"},
            "usage": {
                "input_tokens": 23,
                "output_tokens": 5,
                "iterations": [
                    {"type": "compaction", "input_tokens": 100, "output_tokens": 7},
                    {"type": "message", "input_tokens": 23, "output_tokens": 5},
                ],
            },
        },
        {"type": "message_stop"},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_sse_body(sse_events),
        )

    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    def patched_async_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr("opensquilla.provider.anthropic.httpx.AsyncClient", patched_async_client)

    provider = AnthropicProvider(api_key="test", model="claude-opus-4-7")

    async def _collect() -> DoneEvent:
        done: DoneEvent | None = None
        async for ev in provider.chat([Message(role="user", content="hi")], config=ChatConfig()):
            if isinstance(ev, DoneEvent):
                done = ev
        assert done is not None
        return done

    done = asyncio.run(_collect())
    assert done.input_tokens == 123
    assert done.output_tokens == 12


@pytest.mark.parametrize(
    "creation_payload,expected",
    [
        ({"cache_creation_input_tokens": 250}, 250),
        (
            {"cache_creation": {"ephemeral_5m_input_tokens": 100, "ephemeral_1h_input_tokens": 50}},
            150,
        ),
    ],
)
def test_anthropic_done_event_cache_write_handles_both_shapes(
    monkeypatch, creation_payload, expected
) -> None:
    sse_events = [
        {
            "type": "message_start",
            "message": {
                "id": "msg_1",
                "model": "claude-opus-4-7",
                "usage": {"input_tokens": 1, **creation_payload},
            },
        },
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_stop", "index": 0},
        {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn"},
            "usage": {"output_tokens": 1, **creation_payload},
        },
        {"type": "message_stop"},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_sse_body(sse_events),
        )

    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    def patched_async_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr("opensquilla.provider.anthropic.httpx.AsyncClient", patched_async_client)

    provider = AnthropicProvider(api_key="test", model="claude-opus-4-7")

    async def _collect() -> DoneEvent:
        done: DoneEvent | None = None
        async for ev in provider.chat([Message(role="user", content="hi")], config=ChatConfig()):
            if isinstance(ev, DoneEvent):
                done = ev
        assert done is not None
        return done

    done = asyncio.run(_collect())
    assert done.cache_write_tokens == expected


def test_anthropic_http_error_with_non_utf8_body_yields_error_event(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            headers={"content-type": "application/json"},
            content=b"\xffrate limited",
        )

    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    def patched_async_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr("opensquilla.provider.anthropic.httpx.AsyncClient", patched_async_client)
    provider = AnthropicProvider(api_key="test", model="claude-opus-4-7")

    async def _collect() -> list[object]:
        return [
            event
            async for event in provider.chat(
                [Message(role="user", content="hi")],
                config=ChatConfig(),
            )
        ]

    events = asyncio.run(_collect())

    assert len(events) == 1
    error = events[0]
    assert isinstance(error, ErrorEvent)
    assert error.code == "429"
    assert error.message.startswith("HTTP 429:")
