"""Standalone local path slash-command workflow for interactive chat."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from opensquilla.cli.attachments import (
    path_prompt_and_attachments as build_path_prompt_and_attachments,
)
from opensquilla.cli.repl.session_state import ChatSessionState
from opensquilla.cli.repl.stream import TurnResult
from opensquilla.cli.ui import console, error_panel

PathPromptBuilder = Callable[[str], tuple[str, list[dict[str, Any]]]]
StreamResponse = Callable[..., Awaitable[TurnResult]]


async def handle_standalone_path_command(
    command: str,
    parts: Sequence[str],
    state: ChatSessionState,
    *,
    turn_runner: object,
    tool_context: object,
    services: object,
    model: str | None,
    timeout: float | None,
    stream_response: StreamResponse,
    path_prompt_and_attachments: PathPromptBuilder = build_path_prompt_and_attachments,
) -> bool:
    """Handle standalone chat /path without creating upload attachments."""

    if len(parts) == 1 or not parts[1].strip():
        console.print("[red]Usage: /path <path> \\[prompt][/red]")
        return True

    try:
        prompt, attachments = path_prompt_and_attachments(command)
    except ValueError as exc:
        console.print(error_panel(str(exc)))
        return True

    if attachments:
        console.print(error_panel("/path must not create attachments."))
        return True

    result = await stream_response(
        turn_runner,
        state.session_key,
        tool_context,
        prompt,
        model=model,
        svc=services,
        timeout=timeout,
    )
    state.transcript.add("user", prompt)
    state.transcript.add("assistant", result.text)
    state.usage.add(result.usage)
    return True
