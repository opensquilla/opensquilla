"""Scheduler-owned cron route/tool-context construction."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from opensquilla.session.keys import normalize_agent_id, parse_agent_id
from opensquilla.tools.policy import apply_tool_policy_layer
from opensquilla.tools.types import (
    CRON_AGENT_ALLOW,
    CRON_AGENT_DENY,
    CallerKind,
    InteractionMode,
    ToolContext,
)


class SourceKind(StrEnum):
    """Scheduler route source kinds."""

    CRON = "cron"


@dataclass(frozen=True)
class ReplyTarget:
    """External channel target that can receive cron delivery."""

    kind: str
    channel_name: str | None = None
    channel_type: str | None = None
    to: str | None = None
    account_id: str | None = None
    thread_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CronRouteEnvelope:
    """Canonical routing data for scheduler-originated turns."""

    source_kind: SourceKind
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
    reply_target: ReplyTarget | None = None
    input_provenance: dict[str, Any] = field(default_factory=dict)
    delivery_context: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    interaction_mode: InteractionMode = InteractionMode.UNATTENDED

    def delivery_fields(self) -> dict[str, Any]:
        """Return session routing fields derived from the reply target."""
        target = self.reply_target
        if target is None or target.kind != "channel":
            return {}
        return {
            "last_channel": target.channel_name,
            "last_to": target.to,
            "last_account_id": target.account_id,
            "last_thread_id": target.thread_id,
            "delivery_context": dict(self.delivery_context),
        }

    def tool_context(
        self,
        *,
        is_owner: bool = False,
        workspace_dir: str | None = None,
        workspace_strict: bool = False,
    ) -> ToolContext:
        """Build the ToolContext for this scheduler route."""
        return tool_context_from_envelope(
            self,
            is_owner=is_owner,
            workspace_dir=workspace_dir,
            workspace_strict=workspace_strict,
        )


def _agent_id(agent_id: str | None, session_key: str) -> str:
    return normalize_agent_id(agent_id) if agent_id else parse_agent_id(session_key)


def build_cron_route_envelope(
    job: Any,
    *,
    session_key: str,
    agent_id: str | None = None,
    delivery: Any | None = None,
) -> CronRouteEnvelope:
    """Build a route for scheduler-originated agent work or delivery."""
    resolved_delivery = delivery if delivery is not None else getattr(job, "delivery", None)
    job_id = str(getattr(job, "id", "unknown"))
    job_name = str(getattr(job, "name", ""))
    sender_id = f"cron-job-{job_id}"
    metadata: dict[str, Any] = {"job_id": job_id, "job_name": job_name}
    tool_policy = getattr(job, "tool_policy", None)
    if isinstance(tool_policy, dict) and tool_policy:
        metadata["tool_policy"] = dict(tool_policy)
    reply_target = None
    delivery_context = {
        "sender_id": sender_id,
        "channel_id": "",
        "job_id": job_id,
        "job_name": job_name,
    }
    if (
        resolved_delivery is not None
        and getattr(resolved_delivery, "mode", None) != "none"
        and getattr(resolved_delivery, "channel_name", "")
    ):
        channel_name = getattr(resolved_delivery, "channel_name", "")
        channel_id = getattr(resolved_delivery, "channel_id", "")
        account_id = getattr(resolved_delivery, "account_id", "")
        thread_id = getattr(resolved_delivery, "thread_id", "")
        reply_target = ReplyTarget(
            kind="channel",
            channel_name=channel_name,
            channel_type=channel_name,
            to=channel_id,
            account_id=account_id or None,
            thread_id=thread_id or None,
        )
        delivery_context["channel_id"] = channel_id
    return CronRouteEnvelope(
        source_kind=SourceKind.CRON,
        source_name="cron",
        agent_id=_agent_id(agent_id, session_key),
        session_key=session_key,
        sender_id=sender_id,
        channel_type="cron",
        channel_name="cron",
        channel_id=f"cron:{job_id}",
        reply_target=reply_target,
        input_provenance={"kind": "cron_job", "job_id": job_id},
        delivery_context=delivery_context,
        metadata=metadata,
        interaction_mode=InteractionMode.UNATTENDED,
    )


def tool_context_from_envelope(
    envelope: CronRouteEnvelope,
    *,
    is_owner: bool = False,
    workspace_dir: str | None = None,
    workspace_strict: bool = False,
) -> ToolContext:
    """Build the runtime ToolContext from a scheduler route envelope."""
    interaction_mode = (
        envelope.interaction_mode
        if isinstance(envelope.interaction_mode, InteractionMode)
        else InteractionMode(str(envelope.interaction_mode))
    )
    ctx = ToolContext(
        is_owner=is_owner,
        caller_kind=CallerKind.CRON,
        interaction_mode=interaction_mode,
        agent_id=envelope.agent_id,
        workspace_dir=workspace_dir,
        workspace_strict=workspace_strict,
        session_key=envelope.session_key,
        channel_kind=envelope.channel_name or envelope.channel_type,
        channel_id=envelope.channel_id,
        sender_id=envelope.sender_id,
        source_kind=envelope.source_kind.value,
        source_name=envelope.source_name,
        allowed_tools=set(CRON_AGENT_ALLOW),
        denied_tools=set(CRON_AGENT_DENY),
    )
    return apply_tool_policy_layer(
        ctx,
        envelope.metadata.get("tool_policy"),
        available_tools=CRON_AGENT_ALLOW | CRON_AGENT_DENY,
        hard_denied=CRON_AGENT_DENY,
    )
