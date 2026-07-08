"""Shared streaming-assembly helpers for provider adapters.

Each provider keeps its own transport loop and raw-format detection (SSE vs
JSONL vs whole-response; differing field names). What they had all duplicated
is the *semantic* bookkeeping inside that loop: buffering reasoning fragments
into ``DoneEvent.reasoning_content``, and assembling streamed tool-call
fragments into the ToolUseStart/Delta/End lifecycle. That logic lives here
once.

The accumulators are deliberately format-agnostic: a provider feeds them the
fragments it has already extracted from its own wire format and yields the
events they return, so the lifecycle invariants (one Start per call, a stable
``tool_use_id`` across Start/Delta/End, exactly one End per call — including
for streams truncated before the upstream closed its blocks) are enforced in
one place instead of four.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from opensquilla.provider.types import (
    ReasoningDeltaEvent,
    StreamEvent,
    ToolUseDeltaEvent,
    ToolUseEndEvent,
    ToolUseStartEvent,
)


class ReasoningAccumulator:
    """Buffers reasoning fragments and emits them as streaming deltas.

    Usage in a provider loop::

        racc = ReasoningAccumulator()
        ...
        if fragment := extract_reasoning(chunk):
            event = racc.emit(fragment)
            if event is not None:
                yield event
        ...
        done = DoneEvent(reasoning_content=racc.finalize(), ...)
    """

    __slots__ = ("_parts",)

    def __init__(self) -> None:
        self._parts: list[str] = []

    def emit(self, fragment: str | None) -> ReasoningDeltaEvent | None:
        """Buffer a reasoning fragment; return an event to yield, or None.

        Empty/None fragments are ignored (no event), matching the providers'
        prior behavior of skipping empty reasoning chunks.
        """
        if not fragment:
            return None
        self._parts.append(fragment)
        return ReasoningDeltaEvent(text=fragment)

    def finalize(self) -> str | None:
        """Return the joined reasoning text, or None if nothing was buffered.

        ``None`` (not ``""``) when empty preserves the existing
        ``DoneEvent.reasoning_content`` contract, where absence of reasoning is
        represented as ``None``.
        """
        if not self._parts:
            return None
        return "".join(self._parts)

    @property
    def has_content(self) -> bool:
        return bool(self._parts)


def parse_tool_arguments(joined_json: str) -> dict[str, Any]:
    """Parse accumulated tool-call JSON; degrade malformed input to ``_raw``.

    Empty input means the model sent a zero-argument call: ``{}``.
    """
    if not joined_json:
        return {}
    try:
        arguments = json.loads(joined_json)
    except json.JSONDecodeError:
        return {"_raw": joined_json}
    if not isinstance(arguments, dict):
        return {"_raw": joined_json}
    return arguments


@dataclass
class _PendingToolCall:
    tool_use_id: str
    tool_name: str
    wire_id: str | None = None
    json_parts: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class ToolStreamAccumulator:
    """Assembles streamed tool-call fragments into Start/Delta/End events.

    Calls are keyed by the provider's *stream-local* identifier — the
    ``tool_calls[].index`` int for OpenAI Chat, the content-block index for
    Anthropic, the output-item id string for the Responses API. The key is
    distinct from the public ``tool_use_id``: the public id is frozen the
    moment ``ToolUseStartEvent`` is emitted, so Start/Delta/End always agree
    even when the upstream reveals its real id only in a later chunk (the
    late id is retained as ``wire_id`` for key matching only).

    The three provider grammars map onto the operations:

    - identity-first (Anthropic ``content_block_start``): ``start`` then
      ``append`` then ``finish``.
    - identity-on-first-delta (OpenAI Chat): ``append_or_start`` per chunk,
      ``finish_all`` when the stream ends (Chat has no per-call stop event).
    - whole-call (Ollama, Responses, non-stream fallbacks): ``start`` +
      ``append`` + ``finish`` (or ``finish_with_arguments`` when the wire
      format already delivered parsed arguments).

    ``finish_all`` also serves as the truncation guard: a stream that drops
    mid-call must still close every open call before DoneEvent.
    """

    def __init__(self) -> None:
        self._calls: dict[Any, _PendingToolCall] = {}
        self._closed: set[Any] = set()

    # -- queries ----------------------------------------------------------

    @property
    def has_calls(self) -> bool:
        """True once any tool call was started (open or closed)."""
        return bool(self._calls)

    def find_key_for_tool_call_id(self, tool_call_id: str) -> Any | None:
        """Return the key of the call matching a provider tool-call id."""
        for key, call in self._calls.items():
            if tool_call_id in (call.tool_use_id, call.wire_id):
                return key
        return None

    def single_key(self) -> Any | None:
        """Return the only key when exactly one call is being assembled."""
        if len(self._calls) == 1:
            return next(iter(self._calls))
        return None

    def next_int_key(self) -> int:
        """Return the next free integer key (for index-less deltas)."""
        int_keys = [key for key in self._calls if isinstance(key, int)]
        return max(int_keys, default=-1) + 1

    def first_metadata(self, name: str) -> Any | None:
        """Return the first call's metadata value for ``name``, if any."""
        for call in self._calls.values():
            value = call.metadata.get(name)
            if value is not None:
                return value
        return None

    def pending_raw_arguments(self) -> list[tuple[Any, str, str, str]]:
        """Return ``(key, tool_use_id, tool_name, raw_argument_text)`` per open call.

        Providers that post-process argument JSON before closing (e.g.
        dialect-specific repair of malformed fragments) read the accumulated
        raw text here and close each call via ``finish_with_arguments``,
        instead of reaching into private state.
        """
        return [
            (key, call.tool_use_id, call.tool_name, "".join(call.json_parts))
            for key, call in self._calls.items()
            if key not in self._closed
        ]

    # -- lifecycle --------------------------------------------------------

    def start(
        self,
        key: Any,
        *,
        tool_use_id: str,
        tool_name: str,
    ) -> list[StreamEvent]:
        """Open a call whose identity arrived before any argument delta."""
        if key in self._calls:
            # Re-announced identity (defensive): refresh the name only.
            if tool_name:
                self._calls[key].tool_name = tool_name
            return []
        call = _PendingToolCall(
            tool_use_id=tool_use_id,
            tool_name=tool_name,
            wire_id=tool_use_id,
        )
        self._calls[key] = call
        return [ToolUseStartEvent(tool_use_id=call.tool_use_id, tool_name=call.tool_name)]

    def append_or_start(
        self,
        key: Any,
        *,
        tool_call_id: str | None = None,
        tool_name: str = "",
        fragment: str = "",
    ) -> list[StreamEvent]:
        """Feed one OpenAI-Chat-style delta where identity may arrive late.

        Creates the call on first sight (synthesizing a public id when the
        chunk carries none); later chunks may only refresh ``wire_id`` and
        the tool name — never the already-emitted public id.
        """
        events: list[StreamEvent] = []
        call = self._calls.get(key)
        if call is None:
            call = _PendingToolCall(
                tool_use_id=tool_call_id or f"call_{uuid4().hex[:12]}",
                tool_name=tool_name,
                wire_id=tool_call_id,
            )
            self._calls[key] = call
            events.append(
                ToolUseStartEvent(tool_use_id=call.tool_use_id, tool_name=call.tool_name)
            )
        else:
            if tool_call_id:
                call.wire_id = tool_call_id
            if tool_name:
                call.tool_name = tool_name
        if fragment:
            call.json_parts.append(fragment)
            events.append(
                ToolUseDeltaEvent(tool_use_id=call.tool_use_id, json_fragment=fragment)
            )
        return events

    def append(self, key: Any, fragment: str) -> list[StreamEvent]:
        """Append an argument fragment to an already-started call.

        Unknown keys return no events — the caller decides whether that is
        worth a diagnostic (a dropped fragment is a provider-stream defect,
        not a reason to kill the stream).
        """
        call = self._calls.get(key)
        if call is None:
            return []
        call.json_parts.append(fragment)
        return [ToolUseDeltaEvent(tool_use_id=call.tool_use_id, json_fragment=fragment)]

    def set_metadata(self, key: Any, name: str, value: Any) -> None:
        """Attach provider-opaque per-call state (e.g. thought signatures)."""
        call = self._calls.get(key)
        if call is not None:
            call.metadata[name] = value

    def finish(self, key: Any) -> list[StreamEvent]:
        """Close one call, parsing its accumulated JSON arguments."""
        call = self._calls.get(key)
        if call is None or key in self._closed:
            return []
        self._closed.add(key)
        return [
            ToolUseEndEvent(
                tool_use_id=call.tool_use_id,
                tool_name=call.tool_name,
                arguments=parse_tool_arguments("".join(call.json_parts)),
            )
        ]

    def finish_with_arguments(self, key: Any, arguments: dict[str, Any]) -> list[StreamEvent]:
        """Close one call with authoritative already-parsed arguments."""
        call = self._calls.get(key)
        if call is None or key in self._closed:
            return []
        self._closed.add(key)
        return [
            ToolUseEndEvent(
                tool_use_id=call.tool_use_id,
                tool_name=call.tool_name,
                arguments=arguments,
            )
        ]

    def finish_all(self) -> Iterator[StreamEvent]:
        """Close every call not yet finished, in start order."""
        for key in list(self._calls):
            yield from self.finish(key)
