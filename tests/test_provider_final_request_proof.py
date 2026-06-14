from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from opensquilla.provider.anthropic import AnthropicProvider
from opensquilla.provider.openai import OpenAIProvider
from opensquilla.provider.types import (
    ChatConfig,
    ContentBlockImage,
    ContentBlockText,
    ContentBlockToolResult,
    DoneEvent,
    ErrorEvent,
    Message,
    TextSnapshotEvent,
    ToolDefinition,
    ToolInputSchema,
)


def _openai_sse_body(model: str = "test-model") -> bytes:
    chunks = [
        {
            "model": model,
            "choices": [{"delta": {"content": "ok"}, "finish_reason": None}],
        },
        {
            "model": model,
            "choices": [{"delta": {}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 2, "completion_tokens": 1},
        },
    ]
    return b"".join(
        f"data: {json.dumps(chunk)}\n\n".encode() for chunk in chunks
    ) + b"data: [DONE]\n\n"


def _openai_diffusing_sse_body(
    model: str = "mercury-2",
    *,
    null_tool_calls: bool = False,
    corrupt_final_suffix: bool = False,
) -> bytes:
    first_delta: dict[str, Any] = {"content": "n0isy answ3r"}
    if null_tool_calls:
        first_delta["tool_calls"] = None
    final_content = "final answer"
    if corrupt_final_suffix:
        final_content += "\ufffd\ufffd\ufffd"
    chunks = [
        {
            "model": model,
            "choices": [{"delta": first_delta, "finish_reason": None}],
        },
        {
            "model": model,
            "choices": [{"delta": {"content": final_content}, "finish_reason": None}],
        },
        {
            "model": model,
            "choices": [{"delta": {}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2},
        },
    ]
    return b"".join(
        f"data: {json.dumps(chunk)}\n\n".encode() for chunk in chunks
    ) + b"data: [DONE]\n\n"


def _anthropic_sse_body(events: list[dict[str, Any]]) -> bytes:
    parts: list[bytes] = []
    for event in events:
        parts.append(f"event: {event['type']}\n".encode())
        parts.append(f"data: {json.dumps(event)}\n\n".encode())
    return b"".join(parts)


def test_openai_final_request_proof_blocks_oversized_send(monkeypatch: Any) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(500)

    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    def patched_async_client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr("opensquilla.provider.openai.httpx.AsyncClient", patched_async_client)
    provider = OpenAIProvider(api_key="test", model="gpt-test")

    async def run() -> list[Any]:
        return [
            event
            async for event in provider.chat(
                [Message(role="user", content="x" * 5000)],
                config=ChatConfig(provider_request_max_chars=1000),
            )
        ]

    events = asyncio.run(run())

    assert requests == []
    assert isinstance(events[0], ErrorEvent)
    assert events[0].code == "provider_request_budget_exhausted"
    proof = json.loads(events[0].message)
    assert proof["fits"] is False
    assert proof["retry_count"] == 2
    assert proof["top_contributors"][0]["chars"] == 5000


def test_openai_env_request_proof_blocks_as_controlled_error(monkeypatch: Any) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(500)

    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    def patched_async_client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    monkeypatch.setenv("OPENSQUILLA_PROVIDER_REQUEST_PROOF_MAX_CHARS", "1")
    monkeypatch.setattr("opensquilla.provider.openai.httpx.AsyncClient", patched_async_client)
    provider = OpenAIProvider(api_key="test", model="gpt-test")

    async def run() -> list[Any]:
        return [
            event
            async for event in provider.chat(
                [Message(role="user", content="hello")],
                config=ChatConfig(provider_request_max_chars=0),
            )
        ]

    events = asyncio.run(run())

    assert requests == []
    assert isinstance(events[0], ErrorEvent)
    assert events[0].code == "provider_request_budget_exhausted"


def test_openai_final_request_proof_allows_native_image_payload(
    monkeypatch: Any,
) -> None:
    requests: list[httpx.Request] = []
    payloads: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        payloads.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_openai_sse_body(),
        )

    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    def patched_async_client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr("opensquilla.provider.openai.httpx.AsyncClient", patched_async_client)
    provider = OpenAIProvider(
        api_key="test",
        model="vision-test",
        base_url="https://openrouter.ai/api/v1",
        provider_kind="openrouter",
    )
    messages = [
        Message(
            role="user",
            content=[
                ContentBlockText(text="describe this image"),
                ContentBlockImage(
                    source_type="base64",
                    media_type="image/png",
                    data="a" * 5000,
                ),
            ],
        )
    ]

    async def run() -> list[Any]:
        return [
            event
            async for event in provider.chat(
                messages,
                config=ChatConfig(provider_request_max_chars=1000),
            )
        ]

    events = asyncio.run(run())

    assert len(requests) == 1
    assert any(isinstance(event, DoneEvent) for event in events)
    media_url = payloads[0]["messages"][0]["content"][1]["image_url"]["url"]
    assert media_url.startswith("data:image/png;base64,")
    assert len(media_url) > 5000


def test_openai_inception_mercury_diffusing_uses_text_snapshots(
    monkeypatch: Any,
) -> None:
    payloads: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_openai_diffusing_sse_body(),
        )

    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    def patched_async_client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr("opensquilla.provider.openai.httpx.AsyncClient", patched_async_client)
    provider = OpenAIProvider(
        api_key="test",
        model="mercury-2",
        base_url="https://api.inceptionlabs.ai/v1",
    )

    async def run() -> list[Any]:
        return [
            event
            async for event in provider.chat(
                [Message(role="user", content="hello")],
                config=ChatConfig(provider_request_max_chars=1000),
            )
        ]

    events = asyncio.run(run())

    assert payloads[0]["stream"] is True
    assert payloads[0]["model"] == "mercury-2"
    assert payloads[0]["diffusing"] is True
    assert payloads[0]["max_completion_tokens"] == ChatConfig().max_tokens
    assert "max_tokens" not in payloads[0]
    assert [event.text for event in events if isinstance(event, TextSnapshotEvent)] == [
        "n0isy answ3r",
        "final answer",
    ]
    assert any(isinstance(event, DoneEvent) for event in events)


def test_openai_inception_prefixed_mercury_model_is_normalized_for_direct_api(
    monkeypatch: Any,
) -> None:
    payloads: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_openai_diffusing_sse_body(),
        )

    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    def patched_async_client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr("opensquilla.provider.openai.httpx.AsyncClient", patched_async_client)
    provider = OpenAIProvider(
        api_key="test",
        model="inception/mercury-2",
        base_url="https://api.inceptionlabs.ai/v1",
        provider_kind="inception",
    )

    async def run() -> list[Any]:
        return [
            event
            async for event in provider.chat(
                [Message(role="user", content="hello")],
                config=ChatConfig(provider_request_max_chars=1000),
            )
        ]

    events = asyncio.run(run())

    assert payloads[0]["model"] == "mercury-2"
    assert payloads[0]["diffusing"] is True
    assert "max_completion_tokens" in payloads[0]
    assert "max_tokens" not in payloads[0]
    assert any(isinstance(event, TextSnapshotEvent) for event in events)


def test_openai_inception_diffusing_tolerates_null_tool_calls(
    monkeypatch: Any,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_openai_diffusing_sse_body(null_tool_calls=True),
        )

    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    def patched_async_client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr("opensquilla.provider.openai.httpx.AsyncClient", patched_async_client)
    provider = OpenAIProvider(
        api_key="test",
        model="inception/mercury-2",
        base_url="https://api.inceptionlabs.ai/v1",
        provider_kind="inception",
    )

    async def run() -> list[Any]:
        return [
            event
            async for event in provider.chat(
                [Message(role="user", content="hello")],
                config=ChatConfig(provider_request_max_chars=1000),
            )
        ]

    events = asyncio.run(run())

    assert [event.text for event in events if isinstance(event, TextSnapshotEvent)] == [
        "n0isy answ3r",
        "final answer",
    ]
    assert any(isinstance(event, DoneEvent) for event in events)


def test_openai_inception_diffusing_strips_trailing_replacement_chars(
    monkeypatch: Any,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_openai_diffusing_sse_body(corrupt_final_suffix=True),
        )

    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    def patched_async_client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr("opensquilla.provider.openai.httpx.AsyncClient", patched_async_client)
    provider = OpenAIProvider(
        api_key="test",
        model="inception/mercury-2",
        base_url="https://api.inceptionlabs.ai/v1",
        provider_kind="inception",
    )

    async def run() -> list[Any]:
        return [
            event
            async for event in provider.chat(
                [Message(role="user", content="hello")],
                config=ChatConfig(provider_request_max_chars=1000),
            )
        ]

    events = asyncio.run(run())

    assert [event.text for event in events if isinstance(event, TextSnapshotEvent)] == [
        "n0isy answ3r",
        "final answer",
    ]


def test_anthropic_final_request_proof_blocks_oversized_send(monkeypatch: Any) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(500)

    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    def patched_async_client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr("opensquilla.provider.anthropic.httpx.AsyncClient", patched_async_client)
    provider = AnthropicProvider(api_key="test", model="claude-test")

    async def run() -> list[Any]:
        return [
            event
            async for event in provider.chat(
                [Message(role="user", content="x" * 5000)],
                config=ChatConfig(provider_request_max_chars=1000),
            )
        ]

    events = asyncio.run(run())

    assert requests == []
    assert isinstance(events[0], ErrorEvent)
    assert events[0].code == "provider_request_budget_exhausted"
    proof = json.loads(events[0].message)
    assert proof["fits"] is False
    assert proof["retry_count"] == 2


def test_anthropic_env_request_proof_blocks_as_controlled_error(monkeypatch: Any) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(500)

    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    def patched_async_client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    monkeypatch.setenv("OPENSQUILLA_PROVIDER_REQUEST_PROOF_MAX_CHARS", "1")
    monkeypatch.setattr("opensquilla.provider.anthropic.httpx.AsyncClient", patched_async_client)
    provider = AnthropicProvider(api_key="test", model="claude-test")

    async def run() -> list[Any]:
        return [
            event
            async for event in provider.chat(
                [Message(role="user", content="hello")],
                config=ChatConfig(provider_request_max_chars=0),
            )
        ]

    events = asyncio.run(run())

    assert requests == []
    assert isinstance(events[0], ErrorEvent)
    assert events[0].code == "provider_request_budget_exhausted"


def test_anthropic_final_request_proof_allows_native_image_payload(
    monkeypatch: Any,
) -> None:
    requests: list[httpx.Request] = []
    payloads: list[dict[str, Any]] = []

    body = _anthropic_sse_body(
        [
            {
                "type": "message_start",
                "message": {"id": "msg_1", "model": "claude-test", "usage": {}},
            },
            {
                "type": "content_block_delta",
                "delta": {"type": "text_delta", "text": "ok"},
            },
            {"type": "message_delta", "usage": {"output_tokens": 1}},
            {"type": "message_stop"},
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        payloads.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=body,
        )

    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    def patched_async_client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr("opensquilla.provider.anthropic.httpx.AsyncClient", patched_async_client)
    provider = AnthropicProvider(api_key="test", model="claude-test")
    messages = [
        Message(
            role="user",
            content=[
                ContentBlockText(text="describe this image"),
                ContentBlockImage(
                    source_type="base64",
                    media_type="image/png",
                    data="a" * 5000,
                ),
            ],
        )
    ]

    async def run() -> list[Any]:
        return [
            event
            async for event in provider.chat(
                messages,
                config=ChatConfig(provider_request_max_chars=1000),
            )
        ]

    events = asyncio.run(run())

    assert len(requests) == 1
    assert any(isinstance(event, DoneEvent) for event in events)
    media_source = payloads[0]["messages"][0]["content"][1]["source"]
    assert media_source == {
        "type": "base64",
        "media_type": "image/png",
        "data": "a" * 5000,
    }


def _large_schema_tool() -> ToolDefinition:
    return ToolDefinition(
        name="large_schema_tool",
        description="Tool with enough schema text to prove final adapter payload accounting.",
        input_schema=ToolInputSchema(
            properties={
                "payload": {
                    "type": "string",
                    "description": "schema details " * 120,
                }
            },
            required=["payload"],
        ),
    )


def test_openai_final_request_proof_compacts_adapter_payload_with_tools(
    monkeypatch: Any,
) -> None:
    requests: list[httpx.Request] = []
    payloads: list[dict[str, Any]] = []
    proofs: list[dict[str, Any]] = []
    budget = 3600

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        payloads.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_openai_sse_body(),
        )

    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    def patched_async_client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr("opensquilla.provider.openai.httpx.AsyncClient", patched_async_client)
    monkeypatch.setattr(
        "opensquilla.provider.openai.log.info",
        lambda event, **kwargs: (
            proofs.append(kwargs) if event == "provider.request_proof" else None
        ),
    )
    provider = OpenAIProvider(api_key="test", model="gpt-test")
    messages = [
        Message(
            role="user",
            content=[
                ContentBlockToolResult(
                    tool_use_id="call_1",
                    content="tool output " * 500,
                )
            ],
        )
    ]

    async def run() -> list[Any]:
        return [
            event
            async for event in provider.chat(
                messages,
                tools=[_large_schema_tool()],
                config=ChatConfig(
                    system="system prompt " * 20,
                    provider_request_max_chars=budget,
                ),
            )
        ]

    events = asyncio.run(run())

    assert len(requests) == 1
    assert any(isinstance(event, DoneEvent) for event in events)
    assert len(requests[0].content) <= budget
    assert any(
        "provider_request" in message.get("content", "")
        for message in payloads[0]["messages"]
    )
    proof = proofs[-1]
    assert proof["fits"] is True
    assert proof["retry_count"] >= 1
    assert proof["messages_chars"] > 0
    assert proof["tools_chars"] > 0
    assert proof["system_chars"] > 0
    assert proof["top_level_chars"] > 0


def test_anthropic_final_request_proof_compacts_adapter_payload_with_tools(
    monkeypatch: Any,
) -> None:
    requests: list[httpx.Request] = []
    payloads: list[dict[str, Any]] = []
    proofs: list[dict[str, Any]] = []
    budget = 3600
    body = _anthropic_sse_body(
        [
            {
                "type": "message_start",
                "message": {"id": "msg_1", "model": "claude-test", "usage": {}},
            },
            {
                "type": "content_block_delta",
                "delta": {"type": "text_delta", "text": "ok"},
            },
            {"type": "message_delta", "usage": {"output_tokens": 1}},
            {"type": "message_stop"},
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        payloads.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=body,
        )

    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    def patched_async_client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr("opensquilla.provider.anthropic.httpx.AsyncClient", patched_async_client)
    monkeypatch.setattr(
        "opensquilla.provider.anthropic.log.info",
        lambda event, **kwargs: (
            proofs.append(kwargs) if event == "provider.request_proof" else None
        ),
    )
    provider = AnthropicProvider(api_key="test", model="claude-test")
    messages = [
        Message(
            role="user",
            content=[
                ContentBlockToolResult(
                    tool_use_id="call_1",
                    content="tool output " * 500,
                )
            ],
        )
    ]

    async def run() -> list[Any]:
        return [
            event
            async for event in provider.chat(
                messages,
                tools=[_large_schema_tool()],
                config=ChatConfig(
                    system="system prompt " * 20,
                    provider_request_max_chars=budget,
                ),
            )
        ]

    events = asyncio.run(run())

    assert len(requests) == 1
    assert any(isinstance(event, DoneEvent) for event in events)
    assert len(requests[0].content) <= budget
    assert "provider_request" in payloads[0]["messages"][0]["content"][0]["content"]
    proof = proofs[-1]
    assert proof["fits"] is True
    assert proof["retry_count"] >= 1
    assert proof["messages_chars"] > 0
    assert proof["tools_chars"] > 0
    assert proof["system_chars"] > 0
    assert proof["top_level_chars"] > 0
