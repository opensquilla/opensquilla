"""Gemini thought_signature extraction and replay (issue #225).

Tests that the OpenAI-compat provider:
1. Extracts thought_signature from Gemini streaming tool_call responses
2. Passes it through DoneEvent.thinking_signature
3. Replays extra_content.google.thought_signature on the first tool_call
   when building request messages with ContentBlockThinking present
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from opensquilla.provider.openai import OpenAIProvider
from opensquilla.provider.types import (
    ChatConfig,
    ContentBlockThinking,
    ContentBlockToolResult,
    ContentBlockToolUse,
    DoneEvent,
    Message,
    ModelCapabilities,
    ToolDefinition,
    ToolInputSchema,
    ToolUseEndEvent,
)


def _patch_transport_body(monkeypatch: Any, captured: dict[str, Any], body: bytes) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = request.headers
        captured["payload"] = json.loads(request.content.decode("utf-8"))
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

    monkeypatch.setattr("opensquilla.provider.openai.httpx.AsyncClient", patched_async_client)


def _sse(chunks: list[dict[str, Any]]) -> bytes:
    body = b"".join(f"data: {json.dumps(chunk)}\n\n".encode() for chunk in chunks)
    return body + b"data: [DONE]\n\n"


def _collect_events(
    provider: OpenAIProvider,
    cfg: ChatConfig,
    messages: list[Message] | None = None,
    tools: list[ToolDefinition] | None = None,
) -> list[Any]:
    async def _run() -> list[Any]:
        return [
            event
            async for event in provider.chat(
                messages or [Message(role="user", content="hi")],
                config=cfg,
                tools=tools,
            )
        ]

    return asyncio.run(_run())


def _make_gemini_provider() -> OpenAIProvider:
    return OpenAIProvider(
        api_key="test",
        model="google/gemini-3.1-pro-preview",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        provider_kind="gemini",
    )


# ---------------------------------------------------------------------------
# 1. Streaming: thought_signature extraction from tool_calls
# ---------------------------------------------------------------------------


def test_gemini_stream_extracts_thought_signature_from_tool_call(monkeypatch: Any) -> None:
    """Gemini returns thought_signature via extra_content.google on tool_calls.
    Provider must extract it and pass it to DoneEvent.thinking_signature."""
    captured: dict[str, Any] = {}
    sig_value = "context_engineering_is_the_way_to_go"
    chunks = [
        {
            "model": "gemini-3.1-pro-preview",
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "id": "call_fc1",
                                "type": "function",
                                "function": {
                                    "name": "write_file",
                                    "arguments": '{"path":"/tmp/out.txt"}',
                                },
                                "extra_content": {
                                    "google": {
                                        "thought_signature": sig_value,
                                    }
                                },
                            }
                        ]
                    },
                    "finish_reason": None,
                }
            ],
        },
        {
            "model": "gemini-3.1-pro-preview",
            "choices": [{"delta": {}, "finish_reason": "tool_calls"}],
            "usage": {"prompt_tokens": 4, "completion_tokens": 2},
        },
    ]
    _patch_transport_body(monkeypatch, captured, _sse(chunks))
    provider = _make_gemini_provider()
    tool = ToolDefinition(
        name="write_file",
        description="Write a file.",
        input_schema=ToolInputSchema(
            properties={"path": {"type": "string"}},
            required=["path"],
        ),
    )
    cfg = ChatConfig(
        thinking=True,
        model_capabilities=ModelCapabilities(
            supports_reasoning=True,
            reasoning_format="gemini",
        ),
    )

    events = _collect_events(provider, cfg, tools=[tool])

    done = next(e for e in events if isinstance(e, DoneEvent))
    assert done.thinking_signature == sig_value
    tool_end = next(e for e in events if isinstance(e, ToolUseEndEvent))
    assert tool_end.tool_name == "write_file"


def test_gemini_stream_parallel_tool_calls_extracts_signature_from_first(
    monkeypatch: Any,
) -> None:
    """Gemini attaches thought_signature only to the first tool_call in parallel calls."""
    captured: dict[str, Any] = {}
    sig_value = "sig_parallel_abc"
    chunks = [
        {
            "model": "gemini-3.1-pro-preview",
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "id": "call_weather_paris",
                                "type": "function",
                                "function": {
                                    "name": "get_weather",
                                    "arguments": '{"city":"Paris"}',
                                },
                                "extra_content": {"google": {"thought_signature": sig_value}},
                            },
                            {
                                "id": "call_weather_london",
                                "type": "function",
                                "function": {
                                    "name": "get_weather",
                                    "arguments": '{"city":"London"}',
                                },
                            },
                        ]
                    },
                    "finish_reason": None,
                }
            ],
        },
        {
            "model": "gemini-3.1-pro-preview",
            "choices": [{"delta": {}, "finish_reason": "tool_calls"}],
            "usage": {"prompt_tokens": 6, "completion_tokens": 3},
        },
    ]
    _patch_transport_body(monkeypatch, captured, _sse(chunks))
    provider = _make_gemini_provider()
    tools = [
        ToolDefinition(
            name="get_weather",
            description="Get weather for a city.",
            input_schema=ToolInputSchema(
                properties={"city": {"type": "string"}},
                required=["city"],
            ),
        ),
    ]
    cfg = ChatConfig(
        thinking=True,
        model_capabilities=ModelCapabilities(
            supports_reasoning=True,
            reasoning_format="gemini",
        ),
    )

    events = _collect_events(provider, cfg, tools=tools)

    done = next(e for e in events if isinstance(e, DoneEvent))
    assert done.thinking_signature == sig_value
    tool_ends = [e for e in events if isinstance(e, ToolUseEndEvent)]
    assert len(tool_ends) == 2


# ---------------------------------------------------------------------------
# 1b. Regression (#233): thought_signature on a non-FC delta
# ---------------------------------------------------------------------------
# Gemini streams thought_signature on the top-level text/thinking delta rather
# than attaching it to a tool_call. The original implementation stored it under
# the string key "__sig__" inside pending_calls (an int-keyed map). When the
# next tool_call arrived without an `index`, _resolve_tool_call_index computed
# max(pending_calls.keys()) + 1 -> "str" + 1 -> TypeError. These tests pin the
# fix: the signature lives outside pending_calls and still reaches DoneEvent.


def test_gemini_stream_signature_on_nonfc_delta_with_tool_call(monkeypatch: Any) -> None:
    """Regression (#233): top-level thought_signature + a tool_call without
    `index` in the same chunk must not raise TypeError. The streamed signature
    must still surface on DoneEvent.thinking_signature."""
    captured: dict[str, Any] = {}
    sig_value = "nonfc_sig_regression"
    chunks = [
        {
            "model": "gemini-3.1-pro-preview",
            "choices": [
                {
                    "delta": {
                        # signature rides on the top-level (non-FC) delta
                        "thought_signature": sig_value,
                        # tool_call with NO `index` -> triggers _resolve_tool_call_index
                        "tool_calls": [
                            {
                                "id": "call_fc1",
                                "type": "function",
                                "function": {
                                    "name": "write_file",
                                    "arguments": '{"path":"/tmp/out.txt"}',
                                },
                            }
                        ],
                    },
                    "finish_reason": None,
                }
            ],
        },
        {
            "model": "gemini-3.1-pro-preview",
            "choices": [{"delta": {}, "finish_reason": "tool_calls"}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2},
        },
    ]
    _patch_transport_body(monkeypatch, captured, _sse(chunks))
    provider = _make_gemini_provider()
    tool = ToolDefinition(
        name="write_file",
        description="Write a file.",
        input_schema=ToolInputSchema(
            properties={"path": {"type": "string"}},
            required=["path"],
        ),
    )
    cfg = ChatConfig(
        thinking=True,
        model_capabilities=ModelCapabilities(
            supports_reasoning=True,
            reasoning_format="gemini",
        ),
    )

    events = _collect_events(provider, cfg, tools=[tool])

    done = next(e for e in events if isinstance(e, DoneEvent))
    assert done.thinking_signature == sig_value
    tool_end = next(e for e in events if isinstance(e, ToolUseEndEvent))
    assert tool_end.tool_name == "write_file"


def test_gemini_stream_signature_on_nonfc_delta_without_tool_call(monkeypatch: Any) -> None:
    """Regression (#233): a top-level thought_signature on a text-only delta
    (no tool calls at all) must still reach DoneEvent.thinking_signature and
    leave no stray string key in the tool-call accumulator."""
    captured: dict[str, Any] = {}
    sig_value = "thinking_only_sig"
    chunks = [
        {
            "model": "gemini-3.1-pro-preview",
            "choices": [
                {
                    "delta": {"content": "thinking...", "thought_signature": sig_value},
                    "finish_reason": None,
                }
            ],
        },
        {
            "model": "gemini-3.1-pro-preview",
            "choices": [{"delta": {}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 2, "completion_tokens": 1},
        },
    ]
    _patch_transport_body(monkeypatch, captured, _sse(chunks))
    provider = _make_gemini_provider()
    cfg = ChatConfig(
        thinking=True,
        model_capabilities=ModelCapabilities(
            supports_reasoning=True,
            reasoning_format="gemini",
        ),
    )

    events = _collect_events(provider, cfg)

    done = next(e for e in events if isinstance(e, DoneEvent))
    assert done.thinking_signature == sig_value


# ---------------------------------------------------------------------------
# 2. Non-streaming: thought_signature extraction
# ---------------------------------------------------------------------------


def test_gemini_non_stream_extracts_thought_signature(monkeypatch: Any) -> None:
    """Non-stream fallback path also extracts thought_signature from tool_calls."""
    captured: dict[str, Any] = {}
    sig_value = "non_stream_sig"
    # Simulate a non-stream JSON response (the _complete_non_stream path is
    # triggered by stream timeout, but uses the same extraction logic).
    chunks = [
        {
            "model": "gemini-3.1-pro-preview",
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "id": "call_fc1",
                                "type": "function",
                                "function": {
                                    "name": "lookup",
                                    "arguments": '{"q":"test"}',
                                },
                                "extra_content": {
                                    "google": {
                                        "thought_signature": sig_value,
                                    }
                                },
                            }
                        ]
                    },
                    "finish_reason": None,
                }
            ],
        },
        {
            "model": "gemini-3.1-pro-preview",
            "choices": [{"delta": {}, "finish_reason": "tool_calls"}],
            "usage": {"prompt_tokens": 2, "completion_tokens": 1},
        },
    ]
    _patch_transport_body(monkeypatch, captured, _sse(chunks))
    provider = _make_gemini_provider()
    tool = ToolDefinition(
        name="lookup",
        description="Lookup.",
        input_schema=ToolInputSchema(properties={"q": {"type": "string"}}, required=["q"]),
    )
    cfg = ChatConfig(
        thinking=True,
        model_capabilities=ModelCapabilities(
            supports_reasoning=True,
            reasoning_format="gemini",
        ),
    )

    events = _collect_events(provider, cfg, tools=[tool])
    done = next(e for e in events if isinstance(e, DoneEvent))
    assert done.thinking_signature == sig_value


# ---------------------------------------------------------------------------
# 3. Request replay: thought_signature on tool_calls in subsequent requests
# ---------------------------------------------------------------------------


def test_gemini_replays_thought_signature_on_first_tool_call(monkeypatch: Any) -> None:
    """When ContentBlockThinking carries a signature, _build_openai_messages
    must attach extra_content.google.thought_signature to the first tool_call."""
    captured: dict[str, Any] = {}
    _patch_transport_body(
        monkeypatch,
        captured,
        _sse(
            [
                {
                    "model": "gemini-3.1-pro-preview",
                    "choices": [{"delta": {"content": "ok"}, "finish_reason": None}],
                },
                {
                    "model": "gemini-3.1-pro-preview",
                    "choices": [{"delta": {}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 2, "completion_tokens": 1},
                },
            ]
        ),
    )

    provider = _make_gemini_provider()
    sig = "replay_sig_123"
    messages = [
        Message(role="user", content="Check flights"),
        Message(
            role="assistant",
            content=[
                ContentBlockThinking(
                    thinking="I need to check the flight status.",
                    signature=sig,
                ),
                ContentBlockToolUse(
                    id="call_fc1",
                    name="check_flight",
                    input={"flight": "AA100"},
                ),
            ],
        ),
        Message(
            role="user",
            content=[
                ContentBlockToolResult(
                    tool_use_id="call_fc1",
                    content='{"status": "delayed"}',
                )
            ],
        ),
        Message(role="user", content="Now book a taxi"),
    ]
    cfg = ChatConfig(
        thinking=True,
        model_capabilities=ModelCapabilities(
            supports_reasoning=True,
            reasoning_format="gemini",
        ),
    )

    async def _run() -> None:
        async for _ in provider.chat(messages, config=cfg):
            pass

    asyncio.run(_run())

    payload = captured["payload"]
    # Find the assistant message with tool_calls in the messages array
    assistant_msgs = [
        m for m in payload["messages"] if m["role"] == "assistant" and "tool_calls" in m
    ]
    assert len(assistant_msgs) == 1
    tc = assistant_msgs[0]["tool_calls"][0]
    assert tc["extra_content"]["google"]["thought_signature"] == sig


def test_gemini_no_signature_when_no_thinking_block(monkeypatch: Any) -> None:
    """If ContentBlockThinking has no signature, tool_calls should not have extra_content."""
    captured: dict[str, Any] = {}
    _patch_transport_body(
        monkeypatch,
        captured,
        _sse(
            [
                {
                    "model": "gemini-3.1-pro-preview",
                    "choices": [{"delta": {"content": "ok"}, "finish_reason": None}],
                },
                {
                    "model": "gemini-3.1-pro-preview",
                    "choices": [{"delta": {}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 2, "completion_tokens": 1},
                },
            ]
        ),
    )

    provider = _make_gemini_provider()
    messages = [
        Message(role="user", content="Check"),
        Message(
            role="assistant",
            content=[
                ContentBlockToolUse(
                    id="call_fc1",
                    name="check",
                    input={"q": "test"},
                ),
            ],
        ),
        Message(
            role="user",
            content=[
                ContentBlockToolResult(
                    tool_use_id="call_fc1",
                    content="result",
                )
            ],
        ),
        Message(role="user", content="continue"),
    ]
    cfg = ChatConfig(
        thinking=True,
        model_capabilities=ModelCapabilities(
            supports_reasoning=True,
            reasoning_format="gemini",
        ),
    )

    async def _run() -> None:
        async for _ in provider.chat(messages, config=cfg):
            pass

    asyncio.run(_run())

    payload = captured["payload"]
    assistant_msgs = [
        m for m in payload["messages"] if m["role"] == "assistant" and "tool_calls" in m
    ]
    assert len(assistant_msgs) == 1
    # No extra_content should be added when no thinking block with signature
    assert "extra_content" not in assistant_msgs[0]["tool_calls"][0]


def test_gemini_no_signature_when_thinking_block_has_no_signature(monkeypatch: Any) -> None:
    """If ContentBlockThinking exists but signature is None, no extra_content."""
    captured: dict[str, Any] = {}
    _patch_transport_body(
        monkeypatch,
        captured,
        _sse(
            [
                {
                    "model": "gemini-3.1-pro-preview",
                    "choices": [{"delta": {"content": "ok"}, "finish_reason": None}],
                },
                {
                    "model": "gemini-3.1-pro-preview",
                    "choices": [{"delta": {}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 2, "completion_tokens": 1},
                },
            ]
        ),
    )

    provider = _make_gemini_provider()
    messages = [
        Message(role="user", content="Check"),
        Message(
            role="assistant",
            content=[
                ContentBlockThinking(thinking="Hmm", signature=None),
                ContentBlockToolUse(
                    id="call_fc1",
                    name="check",
                    input={"q": "test"},
                ),
            ],
        ),
        Message(
            role="user",
            content=[
                ContentBlockToolResult(
                    tool_use_id="call_fc1",
                    content="result",
                )
            ],
        ),
        Message(role="user", content="continue"),
    ]
    cfg = ChatConfig(
        thinking=True,
        model_capabilities=ModelCapabilities(
            supports_reasoning=True,
            reasoning_format="gemini",
        ),
    )

    async def _run() -> None:
        async for _ in provider.chat(messages, config=cfg):
            pass

    asyncio.run(_run())

    payload = captured["payload"]
    assistant_msgs = [
        m for m in payload["messages"] if m["role"] == "assistant" and "tool_calls" in m
    ]
    assert len(assistant_msgs) == 1
    assert "extra_content" not in assistant_msgs[0]["tool_calls"][0]
