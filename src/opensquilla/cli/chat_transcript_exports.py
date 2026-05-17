"""Transcript export helpers for chat slash commands."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from opensquilla.cli.repl.session_state import ChatSessionState, messages_to_markdown
from opensquilla.cli.ui import console


class SessionHistoryClient(Protocol):
    async def session_history(self, session_key: str, limit: int = 1000) -> dict[str, Any]: ...


def _target_from_save_command(cmd: str, session_key: str) -> Path:
    parts = cmd.split(maxsplit=1)
    if len(parts) > 1:
        return Path(parts[1]).expanduser()
    suffix = session_key.replace(":", "-")
    return Path(f"opensquilla-chat-{suffix}.md")


def _write_transcript(target: Path, markdown: str) -> None:
    target.write_text(markdown, encoding="utf-8")


def emit_transcript_saved(target: Path) -> None:
    """Emit successful transcript save output."""

    console.print(f"[green]Saved transcript:[/green] {target}")


def save_transcript_command(cmd: str, state: ChatSessionState) -> None:
    """Save the in-memory standalone chat transcript."""

    target = _target_from_save_command(cmd, state.session_key)
    _write_transcript(target, state.transcript.to_markdown())
    emit_transcript_saved(target)


async def save_gateway_transcript_command(
    cmd: str,
    state: ChatSessionState,
    client: SessionHistoryClient,
) -> None:
    """Save persisted gateway history, falling back to the in-memory transcript."""

    target = _target_from_save_command(cmd, state.session_key)
    history = await client.session_history(state.session_key, limit=1000)
    messages = history.get("messages") or []
    markdown = messages_to_markdown(messages) if isinstance(messages, list) else ""
    if not markdown.strip():
        markdown = state.transcript.to_markdown()
    _write_transcript(target, markdown)
    emit_transcript_saved(target)
