"""Bridge approval queue lifecycle into operator-facing WS push events.

When a run blocks on an exec/plugin approval, the queue records the request;
this module turns those transitions into ``<namespace>.approval.requested`` /
``<namespace>.approval.resolved`` events pushed to every connection holding
the approvals scope, so UIs can react without polling. Additive only: no
existing event is renamed or reshaped, and clients that ignore these events
keep working unchanged.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

from opensquilla.gateway.scopes import APPROVALS_SCOPE

_EVENT_SUFFIXES = frozenset({"requested", "resolved"})


def approval_event_name(event: str, info: dict[str, Any]) -> str | None:
    """Wire event name for a queue transition, or None for unknown events."""
    if event not in _EVENT_SUFFIXES:
        return None
    namespace = str(info.get("namespace") or "exec")
    return f"{namespace}.approval.{event}"


def build_approval_event_payload(info: dict[str, Any]) -> dict[str, Any]:
    """Build the WS payload for an approval lifecycle event.

    ``info`` mirrors ``ApprovalQueue.status()``. The summary fields follow
    the pending-item shape served by the approvals snapshot so push and
    poll consumers see consistent vocabulary.
    """
    raw_params = info.get("params")
    params: dict[str, Any] = raw_params if isinstance(raw_params, dict) else {}
    command = str(params.get("command") or "")
    if not command:
        argv = params.get("argv")
        if isinstance(argv, list):
            command = " ".join(str(part) for part in argv)
    tool_name = params.get("toolName") or params.get("pluginId") or params.get("action_kind") or ""
    payload: dict[str, Any] = {
        "approval_id": str(info.get("id") or ""),
        "namespace": str(info.get("namespace") or "exec"),
        "session_key": str(params.get("sessionKey") or ""),
        "tool_name": str(tool_name),
        "command": command,
        "agent": str(params.get("agent") or ""),
        "created_at": info.get("created_at"),
    }
    if info.get("resolved"):
        payload["approved"] = bool(info.get("approved"))
    return payload


def register_approval_event_bridge(
    queue: Any,
    event_bridge: Any,
    *,
    schedule: Callable[[Any], Any],
) -> Callable[[], None]:
    """Subscribe ``event_bridge`` to approval queue lifecycle transitions.

    ``schedule`` receives the broadcast coroutine (gateway boot passes
    ``create_background_task``). Returns the listener remove callable.
    """

    def _listener(event: str, info: dict[str, Any]) -> None:
        event_name = approval_event_name(event, info)
        if event_name is None:
            return
        emit_coro = event_bridge.broadcast_scoped(
            event_name,
            build_approval_event_payload(info),
            required_scope=APPROVALS_SCOPE,
        )
        try:
            schedule(emit_coro)
        except RuntimeError:
            emit_coro.close()

    return cast("Callable[[], None]", queue.add_event_listener(_listener))
