"""Session-domain memory preservation orchestration for lifecycle actions."""

from __future__ import annotations

from collections.abc import Container
from dataclasses import dataclass
from typing import Any

from opensquilla.session.keys import normalize_agent_id
from opensquilla.session.lifecycle_flush import (
    LifecycleFlushAction,
    SessionLifecycleFlushFailure,
    execute_lifecycle_flush,
    unavailable_flush_failure_for_transcript,
)


@dataclass(frozen=True)
class LifecycleMemoryPreservation:
    previous_session_id: str | None
    receipt: Any | None
    failure: SessionLifecycleFlushFailure | None = None


async def preserve_lifecycle_memory(
    action: LifecycleFlushAction,
    session_manager: Any,
    flush_service: Any | None,
    key: str,
    session: Any | None,
    *,
    force: bool,
    principal_scopes: Container[str],
) -> LifecycleMemoryPreservation:
    previous_session_id = getattr(session, "session_id", None) if session else None
    transcript = await session_manager.get_transcript(key)

    if flush_service is None:
        return LifecycleMemoryPreservation(
            previous_session_id=previous_session_id,
            receipt=None,
            failure=unavailable_flush_failure_for_transcript(
                action,
                key,
                previous_session_id,
                transcript,
                force=force,
                principal_scopes=principal_scopes,
            ),
        )

    agent_id = normalize_agent_id(getattr(session, "agent_id", None) or "main")
    flush_attempt = await execute_lifecycle_flush(
        action,
        flush_service,
        transcript,
        key,
        agent_id=agent_id,
        session_id=previous_session_id,
    )
    return LifecycleMemoryPreservation(
        previous_session_id=previous_session_id,
        receipt=flush_attempt.receipt,
        failure=flush_attempt.failure,
    )


__all__ = [
    "LifecycleMemoryPreservation",
    "preserve_lifecycle_memory",
]
