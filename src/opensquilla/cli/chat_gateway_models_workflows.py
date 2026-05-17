"""Gateway model list slash-command workflow for interactive chat."""

from __future__ import annotations

from typing import Any, Protocol

from opensquilla.cli.chat_presenters import emit_chat_models_table
from opensquilla.cli.ui import console


class GatewayModelListClient(Protocol):
    async def list_models(self) -> list[dict[str, Any]]: ...


async def handle_gateway_models_command(
    parts: list[str],
    client: GatewayModelListClient,
) -> None:
    """Handle the gateway chat /models command."""

    if len(parts) > 1:
        console.print("[red]Usage: /models[/red]")
        return
    models = await client.list_models()
    emit_chat_models_table(models)
