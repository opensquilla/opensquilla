"""Gateway model slash-route executor for interactive chat."""

from __future__ import annotations

from typing import Protocol

from opensquilla.cli.chat_gateway_models_workflows import (
    GatewayModelListClient,
    handle_gateway_models_command,
)
from opensquilla.cli.chat_model_usage_workflows import (
    ModelUsageClient,
    handle_model_command,
)
from opensquilla.cli.repl.session_state import ChatSessionState

GATEWAY_MODEL_ROUTE_NAMES = frozenset({"models", "model"})


class GatewayModelRouteClient(
    GatewayModelListClient,
    ModelUsageClient,
    Protocol,
):
    pass


async def handle_gateway_model_route_command(
    route_name: str,
    parts: list[str],
    state: ChatSessionState,
    client: GatewayModelRouteClient,
) -> bool:
    """Handle gateway slash routes that list or update models."""

    if route_name == "models":
        await handle_gateway_models_command(parts, client)
        return True

    if route_name == "model":
        await handle_model_command(parts, state, client)
        return True

    return False
