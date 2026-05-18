"""Canonical route envelopes for gateway, CLI, scheduler, and subagent turns."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from opensquilla.channels.types import IncomingMessage
from opensquilla.runtime import routing as runtime_routing
from opensquilla.session.keys import normalize_agent_id, parse_agent_id
from opensquilla.tools.policy import apply_tool_policy_layer
from opensquilla.tools.types import (
    CRON_AGENT_ALLOW,
    CRON_AGENT_DENY,
    SUBAGENT_TOOL_DENY,
    CallerKind,
    InteractionMode,
    ToolContext,
)


class SourceKind(StrEnum):
    """Top-level inbound runtime source."""

    WEB = "web"
    CLI = "cli"
    CHANNEL = "channel"
    CRON = "cron"
    SUBAGENT = "subagent"
    SYSTEM = "system"


@dataclass(frozen=True)
class ReplyTarget:
    """External or subscriber target that can receive a reply/announce."""

    kind: str
    channel_name: str | None = None
    channel_type: str | None = None
    to: str | None = None
    account_id: str | None = None
    thread_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RouteEnvelope:
    """Canonical routing data for one inbound turn request."""

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
    interaction_mode: InteractionMode = InteractionMode.INTERACTIVE

    def delivery_fields(self) -> dict[str, Any]:
        """Return session routing fields derived from the reply target."""
        return delivery_fields_from_envelope(self)

    def tool_context(
        self,
        *,
        is_owner: bool = False,
        workspace_dir: str | None = None,
        workspace_strict: bool = False,
    ) -> ToolContext:
        """Build the ToolContext for this route."""
        return tool_context_from_envelope(
            self,
            is_owner=is_owner,
            workspace_dir=workspace_dir,
            workspace_strict=workspace_strict,
        )


def _agent_id(agent_id: str | None, session_key: str) -> str:
    return normalize_agent_id(agent_id) if agent_id else parse_agent_id(session_key)


def _str_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _thread_id(metadata: dict[str, Any]) -> str | None:
    thread = metadata.get("thread_ts") or metadata.get("thread_id")
    return thread if isinstance(thread, str) and thread else None


def _reply_target_from_route(target: object | None) -> ReplyTarget | None:
    neutral_target = runtime_routing.reply_target_from_route(target)
    if neutral_target is None:
        return None
    return ReplyTarget(
        kind=neutral_target.kind,
        channel_name=neutral_target.channel_name,
        channel_type=neutral_target.channel_type,
        to=neutral_target.to,
        account_id=neutral_target.account_id,
        thread_id=neutral_target.thread_id,
        metadata=dict(neutral_target.metadata),
    )


def normalize_route_envelope(envelope: object) -> RouteEnvelope:
    """Normalize a structural route-like object into the gateway RouteEnvelope."""
    if isinstance(envelope, RouteEnvelope):
        return envelope
    metadata = dict(getattr(envelope, "metadata", {}) or {})
    delivery_context = dict(getattr(envelope, "delivery_context", {}) or {})
    reply_target = _reply_target_from_route(getattr(envelope, "reply_target", None))
    source_kind_value = runtime_routing.source_kind_value(
        getattr(envelope, "source_kind", "system")
    )
    source_kind = SourceKind(source_kind_value)
    source_name = _str_or_none(getattr(envelope, "source_name", None)) or source_kind.value
    interaction_mode = InteractionMode(
        runtime_routing.interaction_mode_value(
            getattr(envelope, "interaction_mode", InteractionMode.INTERACTIVE)
        )
    )
    return RouteEnvelope(
        source_kind=source_kind,
        source_name=source_name,
        agent_id=str(getattr(envelope, "agent_id", "main")),
        session_key=str(getattr(envelope, "session_key", "")),
        session_id=_str_or_none(getattr(envelope, "session_id", None)),
        sender_id=_str_or_none(getattr(envelope, "sender_id", None)),
        account_id=_str_or_none(getattr(envelope, "account_id", None)),
        channel_type=_str_or_none(getattr(envelope, "channel_type", None)),
        channel_name=_str_or_none(getattr(envelope, "channel_name", None)),
        channel_id=_str_or_none(getattr(envelope, "channel_id", None)),
        thread_id=_str_or_none(getattr(envelope, "thread_id", None)),
        reply_target=reply_target,
        input_provenance=dict(getattr(envelope, "input_provenance", {}) or {}),
        delivery_context=delivery_context,
        metadata=metadata,
        interaction_mode=interaction_mode,
    )


def build_channel_route_envelope(
    msg: IncomingMessage,
    *,
    session_key: str,
    session_prefix: str,
    agent_id: str | None = None,
    channel_type: str | None = None,
) -> RouteEnvelope:
    """Build a route for a normalized inbound channel message."""
    metadata = dict(msg.metadata or {})
    resolved_agent_id = _agent_id(agent_id, session_key)
    resolved_channel_type = channel_type or session_prefix
    account_id = metadata.get("account_id")
    if not isinstance(account_id, str) or not account_id:
        account_id = None
    thread_id = _thread_id(metadata)
    delivery_context = {
        "sender_id": msg.sender_id,
        "channel_id": msg.channel_id,
        **metadata,
    }
    return RouteEnvelope(
        source_kind=SourceKind.CHANNEL,
        source_name=session_prefix,
        agent_id=resolved_agent_id,
        session_key=session_key,
        sender_id=msg.sender_id,
        account_id=account_id,
        channel_type=resolved_channel_type,
        channel_name=session_prefix,
        channel_id=msg.channel_id,
        thread_id=thread_id,
        reply_target=ReplyTarget(
            kind="channel",
            channel_name=session_prefix,
            channel_type=resolved_channel_type,
            to=msg.channel_id,
            account_id=account_id,
            thread_id=thread_id,
            metadata=metadata,
        ),
        input_provenance={
            "kind": "channel_message",
            "source": session_prefix,
        },
        delivery_context=delivery_context,
        metadata=metadata,
        interaction_mode=InteractionMode.UNATTENDED,
    )


def build_cli_route_envelope(
    *,
    session_key: str,
    agent_id: str | None = None,
    source_name: str = "run",
    channel_id: str = "cli:agent",
    sender_id: str | None = None,
    session_id: str | None = None,
    principal_is_owner: bool | None = None,
    interaction_mode: InteractionMode | str = InteractionMode.INTERACTIVE,
    elevated: str | None = None,
) -> RouteEnvelope:
    """Build a route for local CLI input."""
    resolved_interaction_mode = _interaction_mode(interaction_mode)
    metadata: dict[str, Any] = {}
    if principal_is_owner is not None:
        metadata["principal_is_owner"] = principal_is_owner
    if elevated in ("bypass", "full"):
        metadata["elevated"] = elevated
    return RouteEnvelope(
        source_kind=SourceKind.CLI,
        source_name=source_name,
        agent_id=_agent_id(agent_id, session_key),
        session_key=session_key,
        session_id=session_id,
        sender_id=sender_id,
        channel_type="cli",
        channel_name="cli",
        channel_id=channel_id,
        input_provenance={"kind": "cli_message", "source": source_name},
        metadata=metadata,
        interaction_mode=resolved_interaction_mode,
    )


def build_web_route_envelope(
    *,
    session_key: str,
    agent_id: str | None = None,
    source_name: str = "web",
    conn_id: str | None = None,
    sender_id: str | None = None,
    channel_id: str | None = None,
    session_id: str | None = None,
    tool_source_kind: str | None = None,
    principal_is_owner: bool | None = None,
) -> RouteEnvelope:
    """Build a route for Web/RPC-originated input."""
    resolved_channel_id = channel_id or (f"web:{conn_id}" if conn_id else "web")
    channel_name = "webchat" if resolved_channel_id.startswith("webchat:") else "web"
    metadata: dict[str, Any] = {"conn_id": conn_id}
    if tool_source_kind:
        metadata["tool_source_kind"] = tool_source_kind
    if principal_is_owner is not None:
        metadata["principal_is_owner"] = principal_is_owner
    return RouteEnvelope(
        source_kind=SourceKind.WEB,
        source_name=source_name,
        agent_id=_agent_id(agent_id, session_key),
        session_key=session_key,
        session_id=session_id,
        sender_id=sender_id,
        channel_type="web",
        channel_name=channel_name,
        channel_id=resolved_channel_id,
        reply_target=ReplyTarget(
            kind="web",
            channel_name=channel_name,
            channel_type="web",
            to=conn_id,
        ),
        input_provenance={"kind": "web_message", "source": source_name},
        delivery_context={"sender_id": sender_id, "channel_id": resolved_channel_id},
        metadata=metadata,
        interaction_mode=InteractionMode.INTERACTIVE,
    )


def build_cron_route_envelope(
    job: Any,
    *,
    session_key: str,
    agent_id: str | None = None,
    delivery: Any | None = None,
) -> RouteEnvelope:
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
    return RouteEnvelope(
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


def build_subagent_route_envelope(
    *,
    session_key: str,
    parent_session_key: str,
    agent_id: str | None = None,
    run_id: str | None = None,
    parent_task_id: str | None = None,
    spawn_depth: int = 0,
    origin: str = "sessions_spawn",
) -> RouteEnvelope:
    """Build a route for a child subagent run."""
    metadata = {
        "parent_session_key": parent_session_key,
        "run_id": run_id,
        "parent_task_id": parent_task_id,
        "spawn_depth": spawn_depth,
        "origin": origin,
    }
    return RouteEnvelope(
        source_kind=SourceKind.SUBAGENT,
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
        interaction_mode=InteractionMode.UNATTENDED,
    )


def delivery_fields_from_envelope(envelope: RouteEnvelope | object) -> dict[str, Any]:
    """Translate a channel-capable route into SessionNode delivery fields."""
    normalized = normalize_route_envelope(envelope)
    target = normalized.reply_target
    if target is None or target.kind != "channel":
        return {}
    return {
        "last_channel": target.channel_name,
        "last_to": target.to,
        "last_account_id": target.account_id,
        "last_thread_id": target.thread_id,
        "delivery_context": dict(normalized.delivery_context),
    }


def tool_context_from_envelope(
    envelope: RouteEnvelope | object,
    *,
    is_owner: bool = False,
    workspace_dir: str | None = None,
    workspace_strict: bool = False,
) -> ToolContext:
    """Build the runtime ToolContext from the canonical route envelope."""
    envelope = normalize_route_envelope(envelope)
    caller_kind = _caller_kind(envelope.source_kind)
    allowed_tools: set[str] | None = None
    denied_tools: set[str] = set()
    interaction_mode = _interaction_mode(envelope.interaction_mode)
    if caller_kind is CallerKind.CRON:
        allowed_tools = set(CRON_AGENT_ALLOW)
        denied_tools = set(CRON_AGENT_DENY)
    elif caller_kind is CallerKind.SUBAGENT:
        denied_tools = set(SUBAGENT_TOOL_DENY)
    source_kind = envelope.metadata.get("tool_source_kind") or envelope.source_kind.value
    source_name = envelope.metadata.get("tool_source_name") or envelope.source_name
    elevated = envelope.metadata.get("elevated")
    if elevated not in ("on", "bypass", "full") or not is_owner:
        elevated = None
    ctx = ToolContext(
        is_owner=is_owner,
        caller_kind=caller_kind,
        interaction_mode=interaction_mode,
        subagent_depth=int(envelope.metadata.get("spawn_depth") or 0),
        agent_id=envelope.agent_id,
        workspace_dir=workspace_dir,
        workspace_strict=workspace_strict,
        session_key=envelope.session_key,
        channel_kind=envelope.channel_name or envelope.channel_type,
        channel_id=envelope.channel_id,
        sender_id=envelope.sender_id,
        source_kind=source_kind,
        source_name=source_name,
        allowed_tools=allowed_tools,
        denied_tools=denied_tools,
        elevated=elevated,
    )
    if caller_kind is CallerKind.CRON:
        ctx = apply_tool_policy_layer(
            ctx,
            envelope.metadata.get("tool_policy"),
            available_tools=CRON_AGENT_ALLOW | CRON_AGENT_DENY,
            hard_denied=CRON_AGENT_DENY,
        )
    return ctx


def _interaction_mode(value: InteractionMode | str) -> InteractionMode:
    if isinstance(value, InteractionMode):
        return value
    return InteractionMode(str(value))


def _caller_kind(source_kind: SourceKind) -> CallerKind:
    source_value = getattr(source_kind, "value", source_kind)
    match str(source_value):
        case SourceKind.WEB.value:
            return CallerKind.WEB
        case SourceKind.CLI.value:
            return CallerKind.CLI
        case SourceKind.CHANNEL.value:
            return CallerKind.CHANNEL
        case SourceKind.CRON.value:
            return CallerKind.CRON
        case SourceKind.SUBAGENT.value:
            return CallerKind.SUBAGENT
        case SourceKind.SYSTEM.value:
            return CallerKind.AGENT
    raise ValueError(f"Unsupported route source kind: {source_kind!r}")
