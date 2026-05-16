"""Stable event DTOs shared across application ports."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol


@dataclass(frozen=True)
class TextDelta:
    kind: Literal["text_delta"] = "text_delta"
    text: str = ""


@dataclass(frozen=True)
class ToolCallStarted:
    kind: Literal["tool_call_started"] = "tool_call_started"
    call_id: str = ""
    tool_name: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolCallFinished:
    kind: Literal["tool_call_finished"] = "tool_call_finished"
    call_id: str = ""
    tool_name: str = ""
    result: Any = None
    is_error: bool = False


@dataclass(frozen=True)
class TurnFinished:
    kind: Literal["turn_finished"] = "turn_finished"
    text: str = ""
    usage: dict[str, int | float | str] = field(default_factory=dict)


@dataclass(frozen=True)
class TurnFailed:
    kind: Literal["turn_failed"] = "turn_failed"
    message: str = ""
    code: str = ""
    details: dict[str, Any] = field(default_factory=dict)


type TurnEvent = TextDelta | ToolCallStarted | ToolCallFinished | TurnFinished | TurnFailed
type EventSink = Callable[[TurnEvent], Awaitable[None]]


class EventPublisherPort(Protocol):
    """Publishes application events to an adapter-owned transport."""

    async def publish(self, event: TurnEvent) -> None: ...


__all__ = [
    "EventPublisherPort",
    "EventSink",
    "TextDelta",
    "ToolCallFinished",
    "ToolCallStarted",
    "TurnEvent",
    "TurnFailed",
    "TurnFinished",
]
