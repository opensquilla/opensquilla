"""Read-only slash-command workflows for interactive gateway chat."""

from __future__ import annotations

from typing import Any, Protocol

from opensquilla.cli.chat_presenters import (
    emit_chat_models_table,
    emit_chat_sessions_table,
)
from opensquilla.cli.ui import console


class SessionListClient(Protocol):
    async def list_sessions(self, limit: int = 50) -> dict[str, Any]: ...


class ModelListClient(Protocol):
    async def list_models(self) -> list[dict[str, Any]]: ...


async def handle_sessions_command(parts: list[str], client: SessionListClient) -> None:
    """Handle the gateway chat /sessions command."""

    limit = 10
    if len(parts) > 1:
        try:
            limit = int(parts[1])
        except ValueError:
            console.print("[red]Usage: /sessions [limit][/red]")
            return
    payload = await client.list_sessions(limit=limit)
    emit_chat_sessions_table(payload.get("sessions", []))


async def handle_models_command(parts: list[str], client: ModelListClient) -> None:
    """Handle the gateway chat /models command."""

    if len(parts) > 1:
        console.print("[red]Usage: /models[/red]")
        return
    models = await client.list_models()
    emit_chat_models_table(models)
