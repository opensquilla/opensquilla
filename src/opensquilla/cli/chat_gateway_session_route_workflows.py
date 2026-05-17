"""Gateway session slash-route executor for interactive chat."""

from __future__ import annotations

from typing import Protocol

from opensquilla.cli.chat_gateway_sessions_workflows import (
    GatewaySessionListClient,
    handle_gateway_sessions_command,
)
from opensquilla.cli.chat_session_workflows import (
    SessionLifecycleClient,
    handle_delete_session_command,
    handle_new_session_command,
    handle_resume_session_command,
)
from opensquilla.cli.repl.session_state import ChatSessionState

GATEWAY_SESSION_ROUTE_NAMES = frozenset({"new", "sessions", "resume", "delete"})


class GatewaySessionRouteClient(
    SessionLifecycleClient,
    GatewaySessionListClient,
    Protocol,
):
    pass


async def handle_gateway_session_route_command(
    route_name: str,
    command: str,
    parts: list[str],
    state: ChatSessionState,
    client: GatewaySessionRouteClient,
) -> bool:
    """Handle gateway slash routes that operate on sessions."""

    if route_name == "new":
        await handle_new_session_command(parts, state, client)
        return True

    if route_name == "sessions":
        await handle_gateway_sessions_command(parts, client)
        return True

    if route_name == "resume":
        await handle_resume_session_command(command, parts, state, client)
        return True

    if route_name == "delete":
        await handle_delete_session_command(command, parts, client)
        return True

    return False
