"""Gateway image slash-command workflow for interactive chat."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence

from opensquilla.cli.repl.session_state import ChatSessionState
from opensquilla.cli.repl.stream import TurnResult
from opensquilla.cli.ui import console, error_panel

ImagePromptBuilder = Callable[[str], tuple[str, list[dict[str, str]]]]
StreamResponse = Callable[..., Awaitable[TurnResult]]


async def handle_gateway_image_command(
    command: str,
    parts: Sequence[str],
    state: ChatSessionState,
    *,
    client: object,
    elevated_state: dict[str, str | None],
    stream_response: StreamResponse,
    image_prompt_and_attachments: ImagePromptBuilder,
) -> bool:
    """Handle gateway chat /image orchestration."""

    if len(parts) == 1 or not parts[1].strip():
        console.print("[red]Usage: /image <path> \\[prompt][/red]")
        return True

    try:
        prompt, attachments = image_prompt_and_attachments(command)
    except ValueError as exc:
        console.print(error_panel(str(exc)))
        return True

    result = await stream_response(
        client,
        state.session_key,
        prompt,
        elevated_state,
        attachments=attachments,
    )
    state.transcript.add("user", prompt)
    state.transcript.add("assistant", result.text)
    state.usage.add(result.usage)
    return True
