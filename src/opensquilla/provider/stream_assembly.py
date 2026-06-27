"""Shared streaming-assembly helpers for provider adapters.

Each provider keeps its own transport loop and raw-format detection (SSE vs
JSONL vs whole-response; differing field names). What they had all duplicated
is the *semantic* bookkeeping inside that loop: buffering reasoning fragments
and joining them into the final ``DoneEvent.reasoning_content``. That logic
lives here once.

The accumulator is deliberately format-agnostic: a provider feeds it the text
fragment it has already extracted from its own wire format, gets back a
``ReasoningDeltaEvent`` to yield in real time, and at end of stream asks for the
joined full text. Real-time streaming is therefore *additive* — the joined
string still equals what providers used to assemble by hand, so every non-TUI
consumer of ``reasoning_content`` (signature replay, persistence, compaction,
cost) is unaffected.
"""

from __future__ import annotations

from opensquilla.provider.types import ReasoningDeltaEvent


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
