"""Gateway utility slash-route executor for interactive chat."""

from __future__ import annotations

from typing import Protocol

from opensquilla.cli.chat_tool_compression_workflows import handle_tool_compress_command
from opensquilla.cli.chat_transcript_exports import (
    SessionHistoryClient,
    save_gateway_transcript_command,
)
from opensquilla.cli.repl.session_state import ChatSessionState

GATEWAY_UTILITY_ROUTE_NAMES = frozenset({"tool_compress", "save"})


class GatewayUtilityRouteClient(
    SessionHistoryClient,
    Protocol,
):
    pass


async def handle_gateway_utility_route_command(
    route_name: str,
    command: str,
    state: ChatSessionState,
    client: GatewayUtilityRouteClient,
) -> bool:
    """Handle gateway slash routes for chat utilities."""

    if route_name == "tool_compress":
        await handle_tool_compress_command(command, client=client)
        return True

    if route_name == "save":
        await save_gateway_transcript_command(command, state, client)
        return True

    return False
