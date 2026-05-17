"""Gateway file slash-command workflow for interactive chat."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Any, Protocol

from opensquilla.cli.repl.session_state import ChatSessionState
from opensquilla.cli.repl.stream import TurnResult
from opensquilla.cli.ui import console, error_panel

AsyncUploadCallable = Callable[[Path, str, str], Awaitable[str]]
StreamResponse = Callable[..., Awaitable[TurnResult]]


class AsyncFilePromptBuilder(Protocol):
    def __call__(
        self,
        command: str,
        *,
        upload_callable: AsyncUploadCallable | None = None,
    ) -> Awaitable[tuple[str, list[dict[str, Any]]]]: ...


class GatewayUploadClient(Protocol):
    async def upload_file(self, path: Path, mime: str, name: str) -> str: ...


async def handle_gateway_file_command(
    command: str,
    parts: Sequence[str],
    state: ChatSessionState,
    *,
    client: GatewayUploadClient,
    elevated_state: dict[str, str | None],
    stream_response: StreamResponse,
    async_file_prompt_and_attachments: AsyncFilePromptBuilder,
) -> bool:
    """Handle gateway chat /file upload and streaming orchestration."""

    if len(parts) == 1 or not parts[1].strip():
        console.print("[red]Usage: /file <path> \\[prompt][/red]")
        return True

    async def _bridge_upload(path: Path, mime: str, name: str) -> str:
        return await client.upload_file(path, mime, name)

    try:
        prompt, attachments = await async_file_prompt_and_attachments(
            command,
            upload_callable=_bridge_upload,
        )
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
