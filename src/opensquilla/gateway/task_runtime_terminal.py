"""Terminal payload helpers for gateway task runtime."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from opensquilla.session.models import AgentTaskStatus
from opensquilla.session.terminal_reply import build_terminal_reply


@dataclass(frozen=True)
class SubagentCompletionEvent:
    """Terminal event for a runtime-backed subagent task."""

    parent_session_key: str
    child_session_key: str
    task_id: str
    status: AgentTaskStatus
    terminal_reason: str
    agent_id: str | None = None
    parent_task_id: str | None = None
    error_class: str | None = None
    error_message: str | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "type": "subagent_completion",
            "parent_session_key": self.parent_session_key,
            "child_session_key": self.child_session_key,
            "task_id": self.task_id,
            "status": self.status.value,
        }
        payload.update(
            build_task_terminal_payload(
                self.status,
                terminal_reason=self.terminal_reason,
                error_class=self.error_class,
                error_message=self.error_message,
            )
        )
        if self.agent_id:
            payload["agent_id"] = self.agent_id
        if self.parent_task_id:
            payload["parent_task_id"] = self.parent_task_id
        return payload


TerminalListener = Callable[[SubagentCompletionEvent], Awaitable[None]]


def build_task_terminal_payload(
    status: AgentTaskStatus,
    terminal_reason: str,
    error_class: str | None = None,
    error_message: str | None = None,
) -> dict[str, Any]:
    """Build the task terminal event payload owned by the runtime boundary."""
    payload: dict[str, Any] = {"terminal_reason": terminal_reason}
    if error_class:
        payload["error_class"] = error_class
    if error_message:
        payload["error_message"] = error_message
    if status != AgentTaskStatus.SUCCEEDED:
        payload["terminal_message"] = build_terminal_reply(
            {
                "status": status,
                "terminal_reason": terminal_reason,
                "error_class": error_class,
                "error_message": error_message,
            }
        )
    return payload


async def notify_subagent_terminal(
    listener: TerminalListener | None,
    *,
    run_kind: str,
    parent_session_key: str | None,
    child_session_key: str,
    task_id: str,
    status: AgentTaskStatus,
    terminal_reason: str,
    agent_id: str | None = None,
    parent_task_id: str | None = None,
    error_class: str | None = None,
    error_message: str | None = None,
) -> None:
    """Notify the parent listener when a subagent task reaches a terminal state."""
    if listener is None or run_kind != "subagent":
        return
    if not isinstance(parent_session_key, str) or not parent_session_key:
        return
    event = SubagentCompletionEvent(
        parent_session_key=parent_session_key,
        child_session_key=child_session_key,
        task_id=task_id,
        status=status,
        terminal_reason=terminal_reason,
        agent_id=agent_id,
        parent_task_id=parent_task_id,
        error_class=error_class,
        error_message=error_message,
    )
    try:
        await listener(event)
    except Exception:  # noqa: BLE001 - listener failures are intentionally silent.
        return


__all__ = [
    "SubagentCompletionEvent",
    "TerminalListener",
    "build_task_terminal_payload",
    "notify_subagent_terminal",
]
