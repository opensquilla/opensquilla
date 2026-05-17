"""Gateway exact slash-route executor for interactive chat."""

from __future__ import annotations

from typing import Protocol

from opensquilla.cli.chat_gateway_help_workflows import handle_gateway_help_command
from opensquilla.cli.chat_gateway_status_workflows import handle_gateway_status_command
from opensquilla.cli.chat_gateway_usage_workflows import (
    GatewayUsageClient,
    handle_gateway_cost_command,
    handle_gateway_usage_command,
)
from opensquilla.cli.chat_session_maintenance_workflows import (
    SessionMaintenanceClient,
    handle_clear_session_command,
    handle_compact_session_command,
)
from opensquilla.cli.repl.session_state import ChatSessionState

GATEWAY_EXACT_ROUTE_NAMES = frozenset(
    {"help", "status", "clear", "compact", "cost", "usage"}
)


class GatewayExactRouteClient(
    SessionMaintenanceClient,
    GatewayUsageClient,
    Protocol,
):
    pass


async def handle_gateway_exact_route_command(
    route_name: str,
    state: ChatSessionState,
    client: GatewayExactRouteClient,
) -> bool:
    """Handle exact gateway slash routes that do not need command parts."""

    if route_name == "help":
        handle_gateway_help_command()
        return True

    if route_name == "status":
        return handle_gateway_status_command(state)

    if route_name == "clear":
        await handle_clear_session_command(state, client)
        return True

    if route_name == "compact":
        await handle_compact_session_command(state, client)
        return True

    if route_name == "cost":
        handle_gateway_cost_command(state)
        return True

    if route_name == "usage":
        await handle_gateway_usage_command(client)
        return True

    return False
