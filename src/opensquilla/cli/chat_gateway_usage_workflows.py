"""Gateway usage slash-command workflows for interactive chat."""

from __future__ import annotations

from typing import Any, Protocol

from opensquilla.cli.repl.session_state import ChatSessionState
from opensquilla.cli.ui import console


class GatewayUsageClient(Protocol):
    async def usage_status(self) -> dict[str, Any]: ...


def handle_gateway_cost_command(state: ChatSessionState) -> None:
    """Handle the gateway chat /cost command."""
    console.print(state.usage.render())


async def handle_gateway_usage_command(client: GatewayUsageClient) -> None:
    """Handle the gateway chat /usage command."""
    payload = await client.usage_status()
    console.print(
        "[dim]aggregate usage: "
        f"{payload.get('totalTokens', 0):,} tok · "
        f"${float(payload.get('totalCostUsd', 0.0) or 0.0):.6f}[/dim]"
    )
