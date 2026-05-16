"""Task runtime contracts."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

from .events import TurnEvent


class TaskStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class TaskEnvelope:
    session_key: str
    source: str = "unknown"
    agent_id: str = "main"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TaskHandle:
    task_id: str
    session_key: str
    status: TaskStatus


class TaskRuntimePort(Protocol):
    async def enqueue(self, envelope: TaskEnvelope, message: str, **kwargs: Any) -> TaskHandle: ...

    async def stream(self, task_id: str) -> AsyncIterator[TurnEvent]: ...

    async def cancel(self, task_id: str) -> None: ...


__all__ = [
    "TaskEnvelope",
    "TaskHandle",
    "TaskRuntimePort",
    "TaskStatus",
]
