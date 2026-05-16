"""Memory subsystem contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class MemoryQuery:
    text: str
    agent_id: str = "main"
    limit: int = 5
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MemoryResult:
    id: str
    text: str
    score: float = 0.0
    source: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class MemoryPort(Protocol):
    async def search(self, query: MemoryQuery) -> list[MemoryResult]: ...

    async def save(
        self,
        *,
        agent_id: str,
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> str: ...


__all__ = [
    "MemoryPort",
    "MemoryQuery",
    "MemoryResult",
]
