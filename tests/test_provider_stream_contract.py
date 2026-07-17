"""Provider stream-termination and tool-call identity contracts.

These lock the chat() protocol invariants (provider/protocol.py):

- The stream never raises out of the generator — internal failures become
  ``ErrorEvent(code="provider_internal")``.
- A streamed tool call keeps ONE ``tool_use_id`` across Start/Delta/End even
  when the upstream supplies its real id only in a later chunk.
- A tool-call delta without ``index`` never fails the stream, on any
  provider kind (Gemini's compat endpoint and local gateways omit it).
- The Anthropic stream always terminates with DoneEvent — including streams
  truncated before ``message_stop`` — closing any open tool calls first.
- Text-to-tool-call synthesis only runs for provider kinds that leak the
  MiniMax text protocol (minimax, openrouter), never for e.g. plain openai.
- A non-UTF-8 HTTP error body from Ollama yields an ErrorEvent, not a crash.
- ``DoneEvent.model`` names the model the response reported, degrading to the
  configured id when the upstream omits it. Its default of ``""``
  (``provider/types.py``) makes an omission silent rather than loud, which is
  why Anthropic and Ollama assert it here; the OpenAI family already reported
  it and is covered by the stream goldens.

  This field is *response space*: a dated snapshot such as
  ``claude-sonnet-4-5-20250929``, which no registry entry joins against. It is
  forensics — it answers "what actually ran", and feeds ``usage.model``.
  Feedback attribution deliberately keys on a different field, the configured
  id at ``final_request.execution.model``; see ``_final_request_model`` in
  ``engine/steps/router_decision_record.py``.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from opensquilla.provider.anthropic import AnthropicProvider
from opensquilla.provider.ollama import OllamaProvider
from opensquilla.provider.openai import OpenAIProvider
from opensquilla.provider.types import (
    ChatConfig,
    DoneEvent,
    ErrorEvent,
    Message,
    ProviderHeartbeatEvent,
    ReasoningDeltaEvent,
    TextDeltaEvent,
    ToolDefinition,
    ToolInputSchema,
    ToolUseDeltaEvent,
    ToolUseEndEvent,
    ToolUseStartEvent,
)

_SEARCH_TOOL = ToolDefinition(
    name="search",
    description="Search things.",
    input_schema=ToolInputSchema(properties={"query": {"type": "string"}}),
)


def _openai_sse(chunks: list[dict[str, Any]]) -> bytes:
    body = b"".join(f"data: {json.dumps(chunk)}\n\n".encode() for chunk in chunks)
    return body + b"data: [DONE]\n\n"


def _anthropic_sse(events: list[dict[str, Any]]) -> bytes:
    parts = []
    for ev in events:
        parts.append(f"event: {ev['type']}\n".encode())
        parts.append(f"data: {json.dumps(ev)}\n\n".encode())
    return b"".join(parts)


def _patch_transport(monkeypatch: Any, module: str, response: httpx.Response) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return response

    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    def patched_async_client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(f"opensquilla.provider.{module}.httpx.AsyncClient", patched_async_client)


def _patch_stream_body(monkeypatch: Any, module: str, body: bytes) -> None:
    _patch_transport(
        monkeypatch,
        module,
        httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body),
    )


def _collect(provider: Any, *, tools: list[ToolDefinition] | None = None) -> list[Any]:
    async def _run() -> list[Any]:
        return [
            ev
            async for ev in provider.chat(
                [Message(role="user", content="hi")],
                tools=tools,
                config=ChatConfig(),
            )
        ]

    return asyncio.run(_run())


# ---------------------------------------------------------------------------
# tool_use_id stability across Start/Delta/End
# ---------------------------------------------------------------------------


def test_tool_use_id_stable_when_real_id_arrives_late(monkeypatch: Any) -> None:
    """A late-arriving provider id must not change the already-emitted id."""
    chunks = [
        # First chunk: index but NO id — Start is emitted with a synthesized id.
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "function": {"name": "search", "arguments": '{"que'},
                            }
                        ]
                    },
                    "finish_reason": None,
                }
            ]
        },
        # Second chunk: the provider's real id shows up.
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_real",
                                "function": {"arguments": 'ry": "x"}'},
                            }
                        ]
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        },
    ]
    _patch_stream_body(monkeypatch, "openai", _openai_sse(chunks))
    provider = OpenAIProvider(api_key="k", model="m", provider_kind="openai")
    events = _collect(provider, tools=[_SEARCH_TOOL])

    starts = [e for e in events if isinstance(e, ToolUseStartEvent)]
    deltas = [e for e in events if isinstance(e, ToolUseDeltaEvent)]
    ends = [e for e in events if isinstance(e, ToolUseEndEvent)]
    assert len(starts) == 1 and len(ends) == 1
    ids = {starts[0].tool_use_id} | {d.tool_use_id for d in deltas} | {ends[0].tool_use_id}
    assert len(ids) == 1, f"tool_use_id diverged across events: {ids}"
    assert ends[0].arguments == {"query": "x"}


def test_missing_index_does_not_fail_stream_for_non_gemini(monkeypatch: Any) -> None:
    """Gateways that omit tool_call index must not kill the stream."""
    chunks = [
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "function": {"name": "search", "arguments": '{"query": "x"}'},
                            }
                        ]
                    },
                    "finish_reason": None,
                }
            ]
        },
        {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
    ]
    _patch_stream_body(monkeypatch, "openai", _openai_sse(chunks))
    provider = OpenAIProvider(api_key="k", model="m", provider_kind="openai")
    events = _collect(provider, tools=[_SEARCH_TOOL])

    assert not any(isinstance(e, ErrorEvent) for e in events)
    ends = [e for e in events if isinstance(e, ToolUseEndEvent)]
    assert len(ends) == 1
    assert ends[0].tool_use_id == "call_1"
    assert ends[0].arguments == {"query": "x"}
    assert any(isinstance(e, DoneEvent) for e in events)


def test_null_tool_calls_delta_is_treated_as_empty(monkeypatch: Any) -> None:
    """OpenAI-compatible gateways may stream ``tool_calls: null``."""
    chunks = [
        {"choices": [{"delta": {"content": "ok", "tool_calls": None}, "finish_reason": None}]},
        {"choices": [{"delta": {}, "finish_reason": "stop"}]},
    ]
    _patch_stream_body(monkeypatch, "openai", _openai_sse(chunks))
    provider = OpenAIProvider(api_key="k", model="m", provider_kind="openai")
    events = _collect(provider, tools=[_SEARCH_TOOL])

    assert not any(isinstance(e, ErrorEvent) for e in events)
    assert any(isinstance(e, DoneEvent) for e in events)


def test_empty_stream_falls_back_to_non_stream_for_policy_kind(monkeypatch: Any) -> None:
    calls: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        calls.append(payload)
        if payload.get("stream") is True:
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=b"data: [DONE]\n\n",
            )
        return httpx.Response(
            200,
            json={
                "model": "kimi-for-coding",
                "choices": [{"message": {"content": "fallback ok"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2},
            },
        )

    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    def patched_async_client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr("opensquilla.provider.openai.httpx.AsyncClient", patched_async_client)
    provider = OpenAIProvider(api_key="k", model="kimi-for-coding", provider_kind="moonshot")
    events = _collect(provider)

    assert len(calls) == 2
    assert calls[0]["stream"] is True
    assert calls[1]["stream"] is False
    assert any(isinstance(e, ProviderHeartbeatEvent) for e in events)
    assert [e.text for e in events if isinstance(e, TextDeltaEvent)] == ["fallback ok"]
    assert any(isinstance(e, DoneEvent) for e in events)


def test_reasoning_only_stream_does_not_trigger_empty_stream_fallback(monkeypatch: Any) -> None:
    """A stream that delivered reasoning deltas is not empty: retrying it
    non-stream would deliver (and bill) the same turn twice."""
    calls: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        calls.append(payload)
        chunks = [
            {
                "choices": [
                    {"delta": {"reasoning_content": "thinking..."}, "finish_reason": None}
                ]
            },
            {"choices": [{"delta": {}, "finish_reason": "stop"}]},
        ]
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_openai_sse(chunks),
        )

    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    def patched_async_client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr("opensquilla.provider.openai.httpx.AsyncClient", patched_async_client)
    provider = OpenAIProvider(api_key="k", model="kimi-for-coding", provider_kind="moonshot")
    events = _collect(provider)

    assert len(calls) == 1
    assert calls[0]["stream"] is True
    assert any(isinstance(e, ReasoningDeltaEvent) for e in events)
    assert any(isinstance(e, DoneEvent) for e in events)


def test_internal_parse_error_yields_error_event_not_raise(monkeypatch: Any) -> None:
    """chat() contract: internal failures become ErrorEvent, never a raise."""
    # "choices" as a string makes the per-choice dict access blow up.
    body = b'data: {"choices": "boom"}\n\ndata: [DONE]\n\n'
    _patch_stream_body(monkeypatch, "openai", body)
    provider = OpenAIProvider(api_key="k", model="m", provider_kind="openai")
    events = _collect(provider)

    errors = [e for e in events if isinstance(e, ErrorEvent)]
    assert len(errors) == 1
    assert errors[0].code == "provider_internal"


# ---------------------------------------------------------------------------
# Text-to-tool-call synthesis gating
# ---------------------------------------------------------------------------

_PLAIN_TOOL_TEXT = 'search{"query": "x"}'
_MINIMAX_XML_TEXT = (
    "<minimax:tool_call>"
    '<invoke name="search"><parameter name="query">x</parameter></invoke>'
    "</minimax:tool_call>"
)


def _text_only_chunks(text: str) -> list[dict[str, Any]]:
    return [
        {"choices": [{"delta": {"content": text}, "finish_reason": None}]},
        {"choices": [{"delta": {}, "finish_reason": "stop"}]},
    ]


def test_text_tool_synthesis_disabled_for_plain_openai(monkeypatch: Any) -> None:
    """Prose ending in name{...} on a non-leaking provider stays prose."""
    _patch_stream_body(monkeypatch, "openai", _openai_sse(_text_only_chunks(_PLAIN_TOOL_TEXT)))
    provider = OpenAIProvider(api_key="k", model="m", provider_kind="openai")
    events = _collect(provider, tools=[_SEARCH_TOOL])
    assert not any(isinstance(e, ToolUseStartEvent) for e in events)


def test_text_tool_synthesis_enabled_for_openrouter(monkeypatch: Any) -> None:
    _patch_stream_body(monkeypatch, "openai", _openai_sse(_text_only_chunks(_PLAIN_TOOL_TEXT)))
    provider = OpenAIProvider(api_key="k", model="m", provider_kind="openrouter")
    events = _collect(provider, tools=[_SEARCH_TOOL])
    ends = [e for e in events if isinstance(e, ToolUseEndEvent)]
    assert len(ends) == 1
    assert ends[0].tool_name == "search"
    assert ends[0].synthetic_from_text is True
    assert ends[0].arguments == {"query": "x"}


def test_minimax_xml_synthesis_for_minimax_kind(monkeypatch: Any) -> None:
    _patch_stream_body(monkeypatch, "openai", _openai_sse(_text_only_chunks(_MINIMAX_XML_TEXT)))
    provider = OpenAIProvider(api_key="k", model="m", provider_kind="minimax")
    events = _collect(provider, tools=[_SEARCH_TOOL])
    ends = [e for e in events if isinstance(e, ToolUseEndEvent)]
    assert len(ends) == 1
    assert ends[0].tool_name == "search"
    assert ends[0].synthetic_from_text is True
    assert ends[0].arguments == {"query": "x"}


# ---------------------------------------------------------------------------
# Anthropic streaming tool calls + termination contract
# ---------------------------------------------------------------------------


def _anthropic_tool_events(*, include_stop: bool) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = [
        {
            "type": "message_start",
            "message": {"id": "msg_1", "model": "claude-x", "usage": {"input_tokens": 7}},
        },
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "tool_use", "id": "toolu_1", "name": "search"},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "input_json_delta", "partial_json": '{"que'},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "input_json_delta", "partial_json": 'ry": "x"}'},
        },
    ]
    if include_stop:
        events.extend(
            [
                {"type": "content_block_stop", "index": 0},
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": "tool_use"},
                    "usage": {"output_tokens": 3},
                },
                {"type": "message_stop"},
            ]
        )
    return events


def test_anthropic_streaming_tool_call_assembly(monkeypatch: Any) -> None:
    """content_block_start → input_json_delta → content_block_stop lifecycle."""
    body = _anthropic_sse(_anthropic_tool_events(include_stop=True))
    _patch_stream_body(monkeypatch, "anthropic", body)
    provider = AnthropicProvider(api_key="k", model="claude-x")
    events = _collect(provider, tools=[_SEARCH_TOOL])

    starts = [e for e in events if isinstance(e, ToolUseStartEvent)]
    deltas = [e for e in events if isinstance(e, ToolUseDeltaEvent)]
    ends = [e for e in events if isinstance(e, ToolUseEndEvent)]
    dones = [e for e in events if isinstance(e, DoneEvent)]
    assert [s.tool_use_id for s in starts] == ["toolu_1"]
    assert [d.json_fragment for d in deltas] == ['{"que', 'ry": "x"}']
    assert len(ends) == 1
    assert ends[0].tool_use_id == "toolu_1"
    assert ends[0].tool_name == "search"
    assert ends[0].arguments == {"query": "x"}
    assert len(dones) == 1
    assert dones[0].stop_reason == "tool_use"


def test_anthropic_truncated_stream_still_yields_done(monkeypatch: Any) -> None:
    """A stream dropped before message_stop must close tools and emit Done."""
    body = _anthropic_sse(_anthropic_tool_events(include_stop=False))
    _patch_stream_body(monkeypatch, "anthropic", body)
    provider = AnthropicProvider(api_key="k", model="claude-x")
    events = _collect(provider, tools=[_SEARCH_TOOL])

    ends = [e for e in events if isinstance(e, ToolUseEndEvent)]
    dones = [e for e in events if isinstance(e, DoneEvent)]
    assert len(ends) == 1, "open tool call must be closed on truncation"
    assert ends[0].arguments == {"query": "x"}
    assert len(dones) == 1, "stream must terminate with DoneEvent, not fall off the end"
    assert events.index(ends[0]) < events.index(dones[0])


def test_anthropic_internal_error_yields_error_event(monkeypatch: Any) -> None:
    # content_block_start with a tool_use block missing "id" raises KeyError
    # inside the parse loop; the contract demands ErrorEvent, not a raise.
    body = _anthropic_sse(
        [
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "tool_use", "name": "search"},
            },
        ]
    )
    _patch_stream_body(monkeypatch, "anthropic", body)
    provider = AnthropicProvider(api_key="k", model="claude-x")
    events = _collect(provider, tools=[_SEARCH_TOOL])
    errors = [e for e in events if isinstance(e, ErrorEvent)]
    assert len(errors) == 1
    assert errors[0].code == "provider_internal"


# ---------------------------------------------------------------------------
# Ollama error-body decoding
# ---------------------------------------------------------------------------


def test_ollama_non_utf8_error_body_yields_error_event(monkeypatch: Any) -> None:
    response = httpx.Response(
        500,
        headers={"content-type": "text/plain"},
        content=b"\xff\xfe boom",
    )
    _patch_transport(monkeypatch, "ollama", response)
    provider = OllamaProvider(model="llama3")
    events = _collect(provider)
    errors = [e for e in events if isinstance(e, ErrorEvent)]
    assert len(errors) == 1
    assert errors[0].code == "500"
    assert "boom" in errors[0].message


# ---------------------------------------------------------------------------
# DoneEvent.model is always populated
# ---------------------------------------------------------------------------


def _ollama_ndjson(chunks: list[dict[str, Any]]) -> bytes:
    return b"".join(f"{json.dumps(chunk)}\n".encode() for chunk in chunks)


def _done_of(events: list[Any]) -> DoneEvent:
    dones = [e for e in events if isinstance(e, DoneEvent)]
    assert len(dones) == 1
    return dones[0]


def test_anthropic_done_model_reports_what_the_response_named(monkeypatch: Any) -> None:
    """The executed model, not the configured alias.

    An alias like ``claude-sonnet-4-5`` resolves server-side to a dated
    snapshot, and only the response knows which one answered. Reporting the
    alias back would throw that away and make the field a restatement of
    config the caller already had.

    This is forensics, not an attribution key: the registry holds aliases, so
    a dated snapshot joins against nothing. Attribution keys on the configured
    id instead.
    """
    body = _anthropic_sse(
        [
            {
                "type": "message_start",
                "message": {"id": "msg_1", "model": "claude-sonnet-4-5-20250929", "usage": {}},
            },
            {"type": "message_stop"},
        ]
    )
    _patch_stream_body(monkeypatch, "anthropic", body)
    provider = AnthropicProvider(model="claude-sonnet-4-5", api_key="k")
    assert _done_of(_collect(provider)).model == "claude-sonnet-4-5-20250929"


def test_anthropic_done_model_falls_back_to_configured_when_unreported(
    monkeypatch: Any,
) -> None:
    body = _anthropic_sse(
        [
            {"type": "message_start", "message": {"id": "msg_1", "usage": {}}},
            {"type": "message_stop"},
        ]
    )
    _patch_stream_body(monkeypatch, "anthropic", body)
    provider = AnthropicProvider(model="claude-sonnet-4-5", api_key="k")
    assert _done_of(_collect(provider)).model == "claude-sonnet-4-5"


def test_ollama_done_model_reports_what_the_response_named(monkeypatch: Any) -> None:
    body = _ollama_ndjson(
        [
            {"model": "llama3:8b-instruct", "message": {"content": "hi"}},
            {"model": "llama3:8b-instruct", "done": True, "eval_count": 2},
        ]
    )
    _patch_stream_body(monkeypatch, "ollama", body)
    provider = OllamaProvider(model="llama3")
    assert _done_of(_collect(provider)).model == "llama3:8b-instruct"


def test_ollama_done_model_falls_back_to_configured_when_unreported(monkeypatch: Any) -> None:
    body = _ollama_ndjson([{"message": {"content": "hi"}}, {"done": True, "eval_count": 2}])
    _patch_stream_body(monkeypatch, "ollama", body)
    provider = OllamaProvider(model="llama3")
    assert _done_of(_collect(provider)).model == "llama3"
