"""Standalone utility slash-route executor for interactive chat."""

from __future__ import annotations

from typing import Any

from opensquilla.cli.chat_tool_compression_workflows import handle_tool_compress_command
from opensquilla.cli.chat_transcript_exports import save_transcript_command
from opensquilla.cli.repl.session_state import ChatSessionState

STANDALONE_UTILITY_ROUTE_NAMES = frozenset({"tool_compress", "save"})


async def handle_standalone_utility_route_command(
    route_name: str,
    command: str,
    state: ChatSessionState,
    *,
    config: Any,
) -> bool:
    """Handle standalone slash routes for chat utilities."""

    if route_name == "tool_compress":
        await handle_tool_compress_command(command, config=config)
        return True

    if route_name == "save":
        save_transcript_command(command, state)
        return True

    return False
