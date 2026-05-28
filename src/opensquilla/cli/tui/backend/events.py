"""Structured events emitted by the TUI backend runtime."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TuiEventKind(Enum):
    USER_INPUT_ACCEPTED = "user_input_accepted"
    QUEUED_INPUT_PROMOTED = "queued_input_promoted"
    TURN_STARTED = "turn_started"
    TURN_CANCELLED = "turn_cancelled"
    TURN_FINISHED = "turn_finished"
    STATUS_CHANGED = "status_changed"
    APPROVAL_STARTED = "approval_started"
    APPROVAL_FINISHED = "approval_finished"
    TOOL_STARTED = "tool_started"
    TOOL_FINISHED = "tool_finished"
    TEXT_DELTA_EMITTED = "text_delta_emitted"


@dataclass(frozen=True)
class TuiEvent:
    kind: TuiEventKind
    input_text: str | None = None
    message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


type TuiEventSink = Callable[[TuiEvent], None]
