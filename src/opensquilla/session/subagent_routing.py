"""Subagent route envelopes owned by the session/task domain."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from opensquilla.session.keys import normalize_agent_id, parse_agent_id


class SubagentSourceKind(StrEnum):
    SUBAGENT = "subagent"


@dataclass(frozen=True)
class SubagentRouteEnvelope:
    """Routing data for a child subagent run.

    The gateway task runtime consumes this structurally. Keeping this DTO in
    the session layer lets tools enqueue subagents without importing the
    gateway routing adapter.
    """

    source_kind: SubagentSourceKind
    source_name: str
    agent_id: str
    session_key: str
    session_id: str | None = None
    sender_id: str | None = None
    account_id: str | None = None
    channel_type: str | None = None
    channel_name: str | None = None
    channel_id: str | None = None
    thread_id: str | None = None
    reply_target: Any | None = None
    input_provenance: dict[str, Any] = field(default_factory=dict)
    delivery_context: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    interaction_mode: str = "unattended"


def _agent_id(agent_id: str | None, session_key: str) -> str:
    return normalize_agent_id(agent_id) if agent_id else parse_agent_id(session_key)


def build_subagent_route_envelope(
    *,
    session_key: str,
    parent_session_key: str,
    agent_id: str | None = None,
    run_id: str | None = None,
    parent_task_id: str | None = None,
    spawn_depth: int = 0,
    origin: str = "sessions_spawn",
) -> SubagentRouteEnvelope:
    """Build a route for a child subagent run."""
    metadata = {
        "parent_session_key": parent_session_key,
        "run_id": run_id,
        "parent_task_id": parent_task_id,
        "spawn_depth": spawn_depth,
        "origin": origin,
    }
    return SubagentRouteEnvelope(
        source_kind=SubagentSourceKind.SUBAGENT,
        source_name="subagent",
        agent_id=_agent_id(agent_id, session_key),
        session_key=session_key,
        channel_type="subagent",
        channel_name="subagent",
        channel_id=run_id,
        input_provenance={
            "kind": "subagent_task",
            "parent_session_key": parent_session_key,
            "run_id": run_id,
            "parent_task_id": parent_task_id,
        },
        metadata=metadata,
    )
