"""Regression: Anthropic SSE parser must accept ``data:`` without a space.

The SSE spec treats the single space after the field colon as OPTIONAL.
Some Anthropic-compatible gateways emit ``data:{...}`` (no space) and
``event:message_stop`` accordingly. The parser previously required
``data: `` (with the space) and silently dropped every event, ending the
stream before a DoneEvent and surfacing ``provider_stream_incomplete``.

This test mocks a no-space SSE stream and asserts the text delta and the
terminal DoneEvent both come through.
"""

from __future__ import annotations

import asyncio
from typing import Any

from opensquilla.provider import anthropic as anthropic_mod
from opensquilla.provider.anthropic import AnthropicProvider
from opensquilla.provider.types import (
    ChatConfig,
    DoneEvent,
    Message,
    TextDeltaEvent,
)

# SSE lines exactly as a no-space gateway emits them (httpx aiter_lines
# yields one logical line per event field; blank separators included).
_NO_SPACE_SSE_LINES = [
    'event:message_start',
    'data:{"type":"message_start","message":{"usage":{"input_tokens":5}}}',
    '',
    'event:content_block_start',
    'data:{"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}',
    '',
    'event:content_block_delta',
    'data:{"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Hi"}}',
    '',
    'event:content_block_stop',
    'data:{"type":"content_block_stop","index":0}',
    '',
    'event:message_delta',
    'data:{"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":2}}',
    '',
    'event:message_stop',
    'data:{"type":"message_stop"}',
    '',
]


def test_anthropic_sse_without_space_after_colon(monkeypatch: Any) -> None:
    class _StubResponse:
        status_code = 200

        async def aiter_lines(self):
            for line in _NO_SPACE_SSE_LINES:
                yield line

        async def aread(self) -> bytes:
            return b""

        async def __aenter__(self) -> _StubResponse:
            return self

        async def __aexit__(self, *exc: Any) -> None:
            return None

    class _StubClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> _StubClient:
            return self

        async def __aexit__(self, *exc: Any) -> None:
            return None

        def stream(self, *args: Any, **kwargs: Any) -> _StubResponse:
            return _StubResponse()

    monkeypatch.setattr(anthropic_mod.httpx, "AsyncClient", _StubClient)

    provider = AnthropicProvider(api_key="k", model="claude-sonnet-4-6")
    msg = Message(role="user", content="hi")

    async def _run() -> list[Any]:
        out: list[Any] = []
        async for ev in provider.chat([msg], None, ChatConfig()):
            out.append(ev)
        return out

    events = asyncio.run(_run())

    text = "".join(
        e.text for e in events if isinstance(e, TextDeltaEvent)
    )
    assert text == "Hi", f"expected decoded text 'Hi', got {text!r} from {events!r}"
    assert any(isinstance(e, DoneEvent) for e in events), (
        f"expected a terminal DoneEvent (no-space 'data:' must still close "
        f"the stream), got {events!r}"
    )
