"""Channel-side slash-command dispatcher — adapter over the unified registry.

``DEFAULT_COMMAND_REGISTRY`` is derived from
:data:`opensquilla.engine.commands.DEFAULT_REGISTRY` rather than holding its
own hard-coded command table. The ``CommandRegistry.match`` and ``dispatch``
API is preserved for existing callers (``gateway/boot.py``,
``gateway/channel_dispatch.py``).

The channel-side slash-intercept-pre-persist invariant
(``channel_dispatch.py:88-100``) stays where it lives; this module only
provides the dispatch lookup table.
"""

from __future__ import annotations

from typing import Any

from opensquilla.channels.types import OutgoingMessage
from opensquilla.engine.commands import DEFAULT_REGISTRY, ExecutionKind, ParamsFactory, Surface
from opensquilla.gateway.auth import Principal
from opensquilla.gateway.routing import RouteEnvelope, SourceKind
from opensquilla.gateway.rpc import RpcContext
from opensquilla.gateway.scopes import READ_SCOPE, WRITE_SCOPE


class CommandRegistry:
    """Channel-mode dispatcher.

    Matches inbound channel messages against a registered slash-command set
    and forwards the resulting RPC call to the gateway dispatcher. Lookup
    keys are bare command names (without leading slash, lowercased).
    """

    def __init__(self, commands: dict[str, tuple[str, ParamsFactory]]) -> None:
        self._commands = commands

    @property
    def command_names(self) -> set[str]:
        return set(self._commands)

    def match(self, envelope: RouteEnvelope, content: str) -> tuple[str, str, ParamsFactory] | None:
        head = content.strip().split(maxsplit=1)[0] if content.strip() else ""
        if (
            envelope.source_kind is not SourceKind.CHANNEL
            or not head.startswith("/")
            or head == "/"
        ):
            return None
        bare = head[1:].lower()
        command = self._commands.get(bare)
        return (bare, *command) if command else None

    async def dispatch(
        self,
        *,
        envelope: RouteEnvelope,
        message_content: str,
        rpc_dispatcher: Any,
        context_factory: Any,
    ) -> OutgoingMessage | None:
        match = self.match(envelope, message_content)
        if match is None:
            return None
        name, method, params_factory = match
        res = await rpc_dispatcher.dispatch(
            f"channel-command:{name}",
            method,
            params_factory(envelope),
            context_factory(envelope),
        )
        reply_to = envelope.thread_id or envelope.channel_id
        compact_reply = _format_channel_compact_reply(
            name=name,
            method=method,
            res=res,
            reply_to=reply_to,
        )
        if compact_reply is not None:
            return compact_reply
        meta_reply = _format_channel_meta_list_reply(
            name=name,
            method=method,
            res=res,
            reply_to=reply_to,
        )
        if meta_reply is not None:
            return meta_reply
        denied = bool(not res.ok and getattr(res.error, "code", "") == "UNAUTHORIZED")
        reason = "" if res.ok else f": {getattr(res.error, 'message', 'command failed')}"
        state = "completed" if res.ok else ("denied" if denied else "failed")
        return OutgoingMessage(
            content=f"/{name} {state}{reason}",
            reply_to=envelope.thread_id or envelope.channel_id,
            metadata={"command": name, "method": method, "denied": denied},
        )


def _format_channel_compact_reply(
    *,
    name: str,
    method: str,
    res: Any,
    reply_to: str | None,
) -> OutgoingMessage | None:
    if name != "compact" or method != "sessions.contextCompact":
        return None
    denied = bool(not res.ok and getattr(res.error, "code", "") == "UNAUTHORIZED")
    metadata = {"command": name, "method": method, "denied": denied}
    if not res.ok:
        error_message = getattr(res.error, "message", "command failed")
        state = "denied" if denied else "failed"
        return OutgoingMessage(
            content=f"Compact {state}: {error_message}",
            reply_to=reply_to,
            metadata=metadata,
        )
    payload = res.payload if isinstance(res.payload, dict) else {}
    status = str(payload.get("status") or "").lower()
    compacted = bool(payload.get("compacted"))
    if compacted or status == "completed":
        return OutgoingMessage(
            content="Context compacted.",
            reply_to=reply_to,
            metadata=metadata,
        )
    if status == "skipped" or payload.get("compacted") is False:
        return OutgoingMessage(
            content="Already within context budget; no compact was applied.",
            reply_to=reply_to,
            metadata=metadata,
        )
    return OutgoingMessage(
        content="/compact completed",
        reply_to=reply_to,
        metadata=metadata,
    )


def _format_channel_meta_list_reply(
    *,
    name: str,
    method: str,
    res: Any,
    reply_to: str | None,
) -> OutgoingMessage | None:
    if name != "meta" or method != "meta.list":
        return None
    denied = bool(not res.ok and getattr(res.error, "code", "") == "UNAUTHORIZED")
    metadata = {"command": name, "method": method, "denied": denied}
    if not res.ok:
        error_message = getattr(res.error, "message", "command failed")
        state = "denied" if denied else "failed"
        return OutgoingMessage(
            content=f"/meta {state}: {error_message}",
            reply_to=reply_to,
            metadata=metadata,
        )
    payload = res.payload if isinstance(res.payload, dict) else {}
    skills = payload.get("skills") if isinstance(payload.get("skills"), list) else []
    if payload.get("disabled") or not skills:
        return OutgoingMessage(
            content="No meta-skills available.",
            reply_to=reply_to,
            metadata=metadata,
        )
    lines = ["Available meta-skills:"]
    for skill in skills:
        if not isinstance(skill, dict):
            continue
        skill_name = str(skill.get("name") or "")
        description = skill.get("description")
        suffix = f" — {description}" if description else ""
        lines.append(f"- {skill_name}{suffix}")
    return OutgoingMessage(
        content="\n".join(lines),
        reply_to=reply_to,
        metadata=metadata,
    )


def build_channel_rpc_context(
    envelope: RouteEnvelope,
    *,
    gateway_config: Any,
    **handles: Any,
) -> RpcContext:
    admin_senders = getattr(gateway_config, "channel_admin_senders", {})
    sender_id = envelope.sender_id
    is_operator = bool(sender_id and sender_id in admin_senders.get(envelope.source_name, []))
    principal = Principal(
        role="operator" if is_operator else "viewer",
        scopes=frozenset({READ_SCOPE, WRITE_SCOPE}) if is_operator else frozenset(),
        is_owner=False,
        authenticated=True,
    )
    return RpcContext(
        conn_id=f"channel:{envelope.source_name}:{sender_id or 'unknown'}",
        principal=principal,
        config=gateway_config,
        originating_envelope=envelope,
        **handles,
    )


def _build_default_command_table() -> dict[str, tuple[str, ParamsFactory]]:
    """Project the unified registry's CHANNEL surface into the dispatcher table.

    Inserts both the canonical command name and any declared aliases under
    their bare (slash-stripped, lowercase) form so an alias advertised via
    ``commands.list_for_surface`` actually dispatches when typed by a
    channel user. Skips ``CommandDef`` entries that lack RPC metadata —
    channels require a method + params factory to dispatch.
    """
    table: dict[str, tuple[str, ParamsFactory]] = {}
    for cmd in DEFAULT_REGISTRY.for_surface(Surface.CHANNEL):
        execution = cmd.execution_for(Surface.CHANNEL)
        if (
            execution is None
            or execution.kind is not ExecutionKind.RPC
            or execution.rpc_method is None
            or execution.rpc_params is None
        ):
            continue
        for word in cmd.words():
            table[word.lstrip("/").lower()] = (execution.rpc_method, execution.rpc_params)
    return table


DEFAULT_COMMAND_REGISTRY = CommandRegistry(_build_default_command_table())
