"""Push channel approval prompts when a channel-originated run blocks.

When an approval-gated tool call from a channel turn blocks on the queue, the
queue fires a ``requested`` transition. This bridge turns that transition into
an outbound prompt delivered to the originating channel (DM-preferred where the
session's delivery target is a direct chat) so the user who started the turn
can approve or deny with an interactive card or the universal ``/approve
<code>`` text command. On ``resolved`` it releases the short-code binding.

Additive and best-effort: a missing session manager, channel manager, delivery
target, or send failure is swallowed so notification never breaks queue state
or the blocked run (which still expires on its own deadline).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

import structlog

from opensquilla.channels.approval_prompt import (
    ApprovalPromptRequest,
    bind_short_code,
    release_short_code,
    render_approval_prompt,
)
from opensquilla.channels.contract import channel_capability_profile

log = structlog.get_logger(__name__)


def _command_summary(params: dict[str, Any]) -> str:
    command = str(params.get("command") or "")
    if command:
        return command
    return str(params.get("toolName") or params.get("action_kind") or "")


async def _deliver_channel_prompt(
    info: dict[str, Any],
    *,
    session_manager: Any,
    channel_manager: Any,
) -> None:
    params = info.get("params")
    params = params if isinstance(params, dict) else {}
    owner_sender_id = str(params.get("senderId") or "").strip()
    session_key = str(params.get("sessionKey") or "").strip()
    # Only channel-originated requests carry a recorded sender; web/CLI/cron
    # approvals are handled by their own surfaces and must not be re-notified.
    if not owner_sender_id or not session_key:
        return
    if session_manager is None or channel_manager is None:
        return

    get_session = getattr(session_manager, "get_session", None)
    if not callable(get_session):
        return
    try:
        node = await get_session(session_key)
    except Exception:
        return
    if node is None:
        return
    channel_name = getattr(node, "last_channel", None)
    channel_id = getattr(node, "last_to", None)
    thread_id = getattr(node, "last_thread_id", None)
    if not channel_name:
        return

    get_channel = getattr(channel_manager, "get", None)
    if not callable(get_channel):
        return
    adapter = get_channel(channel_name)
    if adapter is None:
        return

    approval_id = str(info.get("id") or "")
    if not approval_id:
        return
    short_code = bind_short_code(
        approval_id,
        namespace=str(info.get("namespace") or "exec"),
        session_key=session_key,
        owner_sender_id=owner_sender_id,
    )
    request = ApprovalPromptRequest(
        approval_id=approval_id,
        namespace=str(info.get("namespace") or "exec"),
        session_key=session_key,
        command_or_tool=_command_summary(params),
        agent=str(params.get("agent") or ""),
        short_code=short_code,
    )
    profile = channel_capability_profile(adapter)
    rendered = render_approval_prompt(profile, request)

    from opensquilla.channels.types import OutgoingMessage

    metadata: dict[str, Any] = {}
    reply_to = thread_id or channel_id
    if channel_name == "slack" and thread_id and channel_id:
        metadata["channel"] = channel_id
    if "card" in rendered:
        metadata["card"] = rendered["card"]
    message = OutgoingMessage(
        content=rendered["text"],
        reply_to=reply_to,
        metadata=metadata,
    )
    try:
        await adapter.send(message)
    except Exception as exc:  # noqa: BLE001 - notification is best-effort.
        log.warning(
            "approval_notify.send_failed",
            channel=channel_name,
            approval_id=approval_id,
            error_type=type(exc).__name__,
            error=str(exc),
        )


def register_approval_channel_notifier(
    queue: Any,
    *,
    session_manager: Any,
    channel_manager_ref: Callable[[], Any],
    schedule: Callable[[Any], Any],
) -> Callable[[], None]:
    """Subscribe a notifier to queue transitions; returns the remove callable.

    ``channel_manager_ref`` is a zero-arg callable so the channel manager can be
    constructed after this bridge is registered (mirrors the boot wiring used by
    other late-bound channel consumers). ``schedule`` receives the delivery
    coroutine (gateway boot passes ``create_background_task``).
    """

    def _listener(event: str, info: dict[str, Any]) -> None:
        if event == "resolved":
            release_short_code(str(info.get("id") or ""))
            return
        if event != "requested":
            return
        params = info.get("params")
        if not isinstance(params, dict) or not str(params.get("senderId") or "").strip():
            return
        coro = _deliver_channel_prompt(
            info,
            session_manager=session_manager,
            channel_manager=channel_manager_ref(),
        )
        try:
            schedule(coro)
        except RuntimeError:
            coro.close()

    return cast("Callable[[], None]", queue.add_event_listener(_listener))
