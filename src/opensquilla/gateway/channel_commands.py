"""Gateway composition helpers for channel slash commands."""

from __future__ import annotations

from typing import Any

from opensquilla.gateway.auth import Principal
from opensquilla.gateway.rpc import RpcContext
from opensquilla.gateway.scopes import READ_SCOPE, WRITE_SCOPE


def build_channel_rpc_context(
    envelope: Any,
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
