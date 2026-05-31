from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from opensquilla.provider import (
    ChatConfig,
    ContentBlockText,
    ContentBlockToolResult,
    ContentBlockToolUse,
    DoneEvent,
    Message,
    TextDeltaEvent,
)
from opensquilla.provider.openai import OpenAIProvider
from opensquilla.provider.openai_responses import OpenAIResponsesProvider
from opensquilla.provider.registry import get_provider_spec
from opensquilla.provider.selector import build_provider


def _patch_transport(
    monkeypatch: Any,
    captured: dict[str, Any],
    response: httpx.Response,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = request.headers
        captured["payload"] = (
            json.loads(request.content.decode("utf-8")) if request.content else None
        )
        return response

    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    def patched_async_client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(
        "opensquilla.provider.openai_responses.httpx.AsyncClient",
        patched_async_client,
    )


def test_openai_responses_provider_is_separate_from_chat_completions_provider() -> None:
    provider = build_provider("openai_responses", "gpt-5.4", api_key="test")

    assert isinstance(provider, OpenAIResponsesProvider)
    assert get_provider_spec("openai_responses").backend == "openai_responses"
    assert get_provider_spec("openai").backend == "openai_compat"
    assert isinstance(
        build_provider("openai", "gpt-5.4", api_key="test"),
        OpenAIProvider,
    )


def test_openai_responses_provider_posts_responses_payload_and_usage(
    monkeypatch: Any,
) -> None:
    captured: dict[str, Any] = {}
    _patch_transport(
        monkeypatch,
        captured,
        httpx.Response(
            200,
            json={
                "id": "resp_test",
                "model": "gpt-5.4",
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "ok",
                                "annotations": [],
                            }
                        ],
                    }
                ],
                "usage": {
                    "input_tokens": 5,
                    "input_tokens_details": {"cached_tokens": 1},
                    "output_tokens": 2,
                    "output_tokens_details": {"reasoning_tokens": 0},
                    "total_tokens": 7,
                },
            },
        ),
    )
    provider = OpenAIResponsesProvider(api_key="test", model="gpt-5.4")

    async def _run() -> list[Any]:
        return [
            event
            async for event in provider.chat(
                [Message(role="user", content="hi")],
                config=ChatConfig(system="stable system", max_tokens=12),
            )
        ]

    events = asyncio.run(_run())

    assert captured["url"] == "https://api.openai.com/v1/responses"
    payload = captured["payload"]
    assert payload["model"] == "gpt-5.4"
    assert payload["instructions"] == "stable system"
    assert payload["input"] == [{"role": "user", "content": "hi"}]
    assert payload["max_output_tokens"] == 12
    assert payload["store"] is False
    assert "messages" not in payload

    assert any(isinstance(event, TextDeltaEvent) and event.text == "ok" for event in events)
    done = next(event for event in events if isinstance(event, DoneEvent))
    assert done.input_tokens == 5
    assert done.cached_tokens == 1
    assert done.output_tokens == 2
    assert done.reasoning_tokens == 0
    assert done.model == "gpt-5.4"


def test_openai_responses_compact_window_returns_opaque_output(
    monkeypatch: Any,
) -> None:
    captured: dict[str, Any] = {}
    compact_output = [
        {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "kept"}],
        },
        {
            "type": "reasoning",
            "encrypted_content": "opaque-encrypted-compaction-item",
        },
    ]
    _patch_transport(
        monkeypatch,
        captured,
        httpx.Response(
            200,
            json={
                "id": "resp_compact",
                "model": "gpt-5.5",
                "output": compact_output,
                "usage": {"input_tokens": 120, "output_tokens": 30},
            },
        ),
    )
    provider = OpenAIResponsesProvider(api_key="test", model="gpt-5.5")
    input_items = [
        {"type": "message", "role": "user", "content": "first"},
        {"type": "message", "role": "assistant", "content": "second"},
    ]

    compacted = asyncio.run(provider.compact_window(input_items))

    assert captured["url"] == "https://api.openai.com/v1/responses/compact"
    assert captured["payload"] == {"model": "gpt-5.5", "input": input_items}
    assert compacted["output"] == compact_output


def test_openai_responses_chat_items_sends_canonical_window_as_input(
    monkeypatch: Any,
) -> None:
    captured: dict[str, Any] = {}
    _patch_transport(
        monkeypatch,
        captured,
        httpx.Response(
            200,
            json={
                "id": "resp_next",
                "model": "gpt-5.5",
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "continued"}],
                    }
                ],
                "usage": {"input_tokens": 12, "output_tokens": 3},
            },
        ),
    )
    provider = OpenAIResponsesProvider(api_key="test", model="gpt-5.5")
    input_items = [
        {"type": "message", "role": "assistant", "content": "retained"},
        {"type": "reasoning", "encrypted_content": "opaque-latest"},
        {"type": "message", "role": "user", "content": "continue"},
    ]

    async def _run() -> list[Any]:
        return [event async for event in provider.chat_items(input_items)]

    events = asyncio.run(_run())

    assert captured["url"] == "https://api.openai.com/v1/responses"
    assert captured["payload"]["input"] == input_items
    assert "messages" not in captured["payload"]
    assert any(isinstance(event, TextDeltaEvent) and event.text == "continued" for event in events)


def test_openai_responses_list_models_uses_model_info_schema(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}
    _patch_transport(
        monkeypatch,
        captured,
        httpx.Response(
            200,
            json={
                "data": [
                    {"id": "gpt-5.5", "name": "GPT 5.5"},
                    {"id": "gpt-5.5-mini"},
                ]
            },
        ),
    )
    provider = OpenAIResponsesProvider(api_key="test", model="gpt-5.5")

    models = asyncio.run(provider.list_models())

    assert captured["url"] == "https://api.openai.com/v1/models"
    assert [(model.provider, model.model_id, model.display_name) for model in models] == [
        ("openai_responses", "gpt-5.5", "GPT 5.5"),
        ("openai_responses", "gpt-5.5-mini", "gpt-5.5-mini"),
    ]


def test_openai_responses_chat_replays_tool_items(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}
    _patch_transport(
        monkeypatch,
        captured,
        httpx.Response(
            200,
            json={
                "id": "resp_tool_followup",
                "model": "gpt-5.5",
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "done"}],
                    }
                ],
                "usage": {"input_tokens": 12, "output_tokens": 2},
            },
        ),
    )
    provider = OpenAIResponsesProvider(api_key="test", model="gpt-5.5")

    async def _run() -> list[Any]:
        return [
            event
            async for event in provider.chat(
                [
                    Message(role="user", content="inspect"),
                    Message(
                        role="assistant",
                        content=[
                            ContentBlockText(text="I will inspect."),
                            ContentBlockToolUse(
                                id="call_read_1",
                                name="read_file",
                                input={"path": "README.md"},
                            ),
                        ],
                    ),
                    Message(
                        role="user",
                        content=[
                            ContentBlockToolResult(
                                tool_use_id="call_read_1",
                                content="README contents",
                            )
                        ],
                    ),
                    Message(role="user", content="continue"),
                ],
                config=ChatConfig(max_tokens=16),
            )
        ]

    asyncio.run(_run())

    assert captured["payload"]["input"] == [
        {"role": "user", "content": "inspect"},
        {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "I will inspect."}],
        },
        {
            "type": "function_call",
            "call_id": "call_read_1",
            "name": "read_file",
            "arguments": '{"path": "README.md"}',
        },
        {
            "type": "function_call_output",
            "call_id": "call_read_1",
            "output": "README contents",
        },
        {"role": "user", "content": "continue"},
    ]
