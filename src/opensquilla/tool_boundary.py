"""Side-effect-free tool-call boundary objects shared across runtime layers."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from opensquilla.execution_status import ExecutionStatus


@dataclass
class ToolCall:
    tool_use_id: str
    tool_name: str
    arguments: dict[str, Any]
    synthetic_from_text: bool = False
    # Optional raw assistant-message origin trace for the tool_use block.
    # Populated by the agent when available; consulted by tools.dispatch to
    # refuse calls whose origin lies inside an <untrusted> envelope.
    origin_trace: str | None = None


@dataclass
class ToolResult:
    tool_use_id: str
    tool_name: str
    content: str
    is_error: bool = False
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    execution_status: ExecutionStatus | None = None
    terminates_turn: bool = False


AgentToolHandler = Callable[[ToolCall], Awaitable[ToolResult]]

# Preserve pickle/type-display identity for callers that imported these
# dataclasses from the previous engine.types path.
ToolCall.__module__ = "opensquilla.engine.types"
ToolResult.__module__ = "opensquilla.engine.types"
