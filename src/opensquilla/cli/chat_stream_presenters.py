"""Presenters for chat streaming status and artifact events."""

from __future__ import annotations

from typing import Any

from opensquilla.artifacts import artifact_payload
from opensquilla.cli.ui import console


def render_gateway_task_group_status(
    event_name: str,
    event: dict[str, Any],
    renderer: Any,
) -> None:
    """Render gateway task-group status without appending to assistant text."""

    phase = event_name.rsplit(".", 1)[-1]
    style = "dim"
    if phase == "waiting":
        pending = event.get("pending_count")
        suffix = f" ({pending} pending)" if isinstance(pending, int) and pending >= 0 else ""
        message = f"subagents waiting{suffix}"
    elif phase == "synthesizing":
        child_count = event.get("child_count")
        suffix = f" from {child_count} children" if isinstance(child_count, int) else ""
        message = f"subagents complete; synthesizing final answer{suffix}"
    elif phase == "done":
        delivery_status = event.get("delivery_status")
        suffix = f" (delivery: {delivery_status})" if isinstance(delivery_status, str) else ""
        message = f"background synthesis complete{suffix}"
    elif phase == "failed":
        error_message = event.get("error_message")
        suffix = f": {error_message}" if isinstance(error_message, str) and error_message else ""
        message = f"background synthesis failed{suffix}"
        style = "yellow"
    else:
        return
    status = getattr(renderer, "status", None)
    if callable(status):
        status(message, style=style)
    else:
        console.print(f"[{style}]{message}[/]")


def artifact_event_payload(event: Any) -> dict[str, Any]:
    """Return a public, sanitized artifact payload for a stream event."""

    if isinstance(event, dict):
        raw = {
            key: value
            for key, value in event.items()
            if key not in {"event", "payload", "session_key", "sessionKey"}
        }
        return artifact_payload(raw)

    return artifact_payload(event)


def artifact_status_line(artifact: dict[str, Any]) -> str:
    """Format the user-visible artifact status line."""

    name = artifact.get("name") if isinstance(artifact.get("name"), str) else "artifact"
    target = artifact.get("download_url") if isinstance(artifact.get("download_url"), str) else ""
    return f"Generated file: {name} -> {target or artifact.get('id', '')}"


def render_artifact_status(artifact: dict[str, Any], renderer: Any) -> None:
    """Render artifact status through renderer status or console fallback."""

    line = artifact_status_line(artifact)
    status = getattr(renderer, "status", None)
    if callable(status):
        status(line)
    else:
        console.print(line)
