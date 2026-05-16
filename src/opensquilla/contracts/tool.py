"""Tool port contracts."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol


class CallerKind(StrEnum):
    AGENT = "agent"
    CHANNEL = "channel"
    CRON = "cron"
    SUBAGENT = "subagent"


class InteractionMode(StrEnum):
    INTERACTIVE = "interactive"
    UNATTENDED = "unattended"


@dataclass(frozen=True)
class ToolContext:
    caller_kind: CallerKind = CallerKind.AGENT
    interaction_mode: InteractionMode = InteractionMode.INTERACTIVE
    is_owner: bool = False
    session_key: str | None = None
    agent_id: str = "main"
    allowed_tools: frozenset[str] | None = None
    denied_tools: frozenset[str] = frozenset()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)
    required: tuple[str, ...] = ()
    owner_only: bool = False
    exposed_by_default: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolResult:
    call_id: str
    content: Any
    is_error: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


type ToolHandler = Callable[[ToolCall, ToolContext], Awaitable[ToolResult]]


class ToolRegistryPort(Protocol):
    def register(self, spec: ToolSpec, handler: ToolHandler) -> None: ...

    def get(self, name: str) -> tuple[ToolSpec, ToolHandler] | None: ...

    def list_specs(self, context: ToolContext | None = None) -> list[ToolSpec]: ...


class ToolPolicyPort(Protocol):
    def filter_tools(self, specs: list[ToolSpec], context: ToolContext) -> list[ToolSpec]: ...


__all__ = [
    "CallerKind",
    "InteractionMode",
    "ToolCall",
    "ToolContext",
    "ToolHandler",
    "ToolPolicyPort",
    "ToolRegistryPort",
    "ToolResult",
    "ToolSpec",
]
