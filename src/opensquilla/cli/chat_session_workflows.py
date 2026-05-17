"""Stateful session slash-command workflows for interactive gateway chat."""

from __future__ import annotations

from typing import Any, Protocol

from opensquilla.cli.repl.session_state import ChatSessionState
from opensquilla.cli.ui import console, error_panel


class SessionLifecycleClient(Protocol):
    async def create_session(
        self,
        agent_id: str = "main",
        model: str | None = None,
        display_name: str | None = None,
    ) -> str: ...

    async def resolve_session(self, key: str) -> dict[str, Any]: ...

    async def delete_sessions(self, keys: list[str]) -> dict[str, Any]: ...


def _reset_chat_session_state(state: ChatSessionState, session_key: str) -> None:
    state.session_key = session_key
    state.transcript.clear()
    state.usage.reset()


async def handle_new_session_command(
    parts: list[str],
    state: ChatSessionState,
    client: SessionLifecycleClient,
) -> None:
    """Handle the gateway chat /new command."""

    title = parts[1].strip() if len(parts) > 1 else None
    session_key = await client.create_session(model=state.model, display_name=title)
    _reset_chat_session_state(state, session_key)
    label = f" ({title})" if title else ""
    console.print(f"[green]Started new session{label}:[/green] {session_key}")


async def handle_resume_session_command(
    cmd: str,
    parts: list[str],
    state: ChatSessionState,
    client: SessionLifecycleClient,
) -> None:
    """Handle the gateway chat /resume command."""

    if len(parts) == 1 or not parts[1].strip():
        console.print("[red]Usage: /resume <id>[/red]")
        return
    target = cmd.split(maxsplit=1)[1].strip()
    payload = await client.resolve_session(target)
    session_key = payload.get("session_key") or payload.get("key") or target
    state.model = payload.get("model") or state.model
    _reset_chat_session_state(state, str(session_key))
    console.print(f"[green]Resumed session:[/green] {state.session_key}")


async def handle_delete_session_command(
    cmd: str,
    parts: list[str],
    client: SessionLifecycleClient,
) -> None:
    """Handle the gateway chat /delete command."""

    if len(parts) == 1 or not parts[1].strip():
        console.print("[red]Usage: /delete <id>[/red]")
        return
    target = cmd.split(maxsplit=1)[1].strip()
    resolved = await client.resolve_session(target)
    session_key = resolved.get("session_key") or resolved.get("key") or target
    payload = await client.delete_sessions([str(session_key)])
    errors = [str(item) for item in payload.get("errors") or []]
    deleted = [str(item) for item in payload.get("deleted") or []]
    if errors:
        console.print(error_panel("\n".join(errors), title="Delete failed"))
    elif deleted:
        console.print(f"[yellow]Deleted session:[/yellow] {deleted[0]}")
    else:
        console.print(error_panel("No session was deleted.", title="Delete failed"))
