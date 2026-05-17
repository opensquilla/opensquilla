"""Gateway image slash-route executor for interactive chat."""

from __future__ import annotations

from collections.abc import Sequence

from opensquilla.cli.chat_gateway_image_workflows import (
    ImagePromptBuilder,
    StreamResponse,
    handle_gateway_image_command,
)
from opensquilla.cli.repl.session_state import ChatSessionState

GATEWAY_IMAGE_ROUTE_NAMES = frozenset({"image"})


async def handle_gateway_image_route_command(
    route_name: str,
    command: str,
    parts: Sequence[str],
    state: ChatSessionState,
    *,
    client: object,
    elevated_state: dict[str, str | None],
    stream_response: StreamResponse,
    image_prompt_and_attachments: ImagePromptBuilder,
) -> bool:
    """Handle gateway slash routes for image attachments."""

    if route_name == "image":
        await handle_gateway_image_command(
            command,
            parts,
            state,
            client=client,
            elevated_state=elevated_state,
            stream_response=stream_response,
            image_prompt_and_attachments=image_prompt_and_attachments,
        )
        return True

    return False
