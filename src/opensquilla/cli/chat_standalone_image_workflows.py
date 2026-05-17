"""Standalone image slash-command workflow for interactive chat."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence

from opensquilla.cli.attachments import image_prompt_from_command as build_image_prompt
from opensquilla.cli.repl.session_state import ChatSessionState
from opensquilla.cli.repl.stream import TurnResult
from opensquilla.cli.ui import console

ImagePromptBuilder = Callable[[str], str]
RunImageCommand = Callable[..., Awaitable[TurnResult]]


async def handle_standalone_image_command(
    command: str,
    parts: Sequence[str],
    state: ChatSessionState,
    *,
    turn_runner: object,
    tool_context: object,
    services: object,
    model: str | None,
    timeout: float | None,
    run_image_command: RunImageCommand,
    image_prompt_from_command: ImagePromptBuilder = build_image_prompt,
) -> bool:
    """Handle standalone chat /image orchestration."""

    if len(parts) == 1 or not parts[1].strip():
        console.print("[red]Usage: /image <path> \\[prompt][/red]")
        return True

    result = await run_image_command(
        turn_runner,
        state.session_key,
        tool_context,
        command,
        model=model,
        svc=services,
        timeout=timeout,
    )
    state.transcript.add("user", image_prompt_from_command(command))
    state.transcript.add("assistant", result.text)
    state.usage.add(result.usage)
    return True
