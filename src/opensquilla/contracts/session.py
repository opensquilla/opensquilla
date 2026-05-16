"""Session and transcript storage contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol


class SessionStatus(StrEnum):
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    KILLED = "killed"
    TIMEOUT = "timeout"


@dataclass(frozen=True)
class SessionRecord:
    session_key: str
    session_id: str
    status: SessionStatus = SessionStatus.RUNNING
    agent_id: str = "main"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TranscriptEntry:
    session_id: str
    role: str
    content: Any
    created_at_ms: int
    metadata: dict[str, Any] = field(default_factory=dict)


class SessionStorePort(Protocol):
    async def get_session(self, session_key: str) -> SessionRecord | None: ...

    async def create_session(self, session: SessionRecord) -> SessionRecord: ...

    async def update_session_status(self, session_key: str, status: SessionStatus) -> None: ...

    async def append_transcript(self, entry: TranscriptEntry) -> None: ...

    async def list_transcript(
        self,
        session_id: str,
        limit: int | None = None,
    ) -> list[TranscriptEntry]: ...


__all__ = [
    "SessionRecord",
    "SessionStatus",
    "SessionStorePort",
    "TranscriptEntry",
]
