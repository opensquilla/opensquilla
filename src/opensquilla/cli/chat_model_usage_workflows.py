"""Model slash-command workflow for interactive gateway chat."""

from __future__ import annotations

from typing import Any, Protocol

from opensquilla.cli.repl.session_state import ChatSessionState
from opensquilla.cli.ui import console


class ModelUsageClient(Protocol):
    async def patch_session(self, key: str, **fields: Any) -> dict[str, Any]: ...


async def handle_model_command(
    parts: list[str],
    state: ChatSessionState,
    client: ModelUsageClient,
) -> None:
    """Handle the gateway chat /model command."""

    if len(parts) == 1:
        console.print(f"[dim]model={state.model or 'default'}[/dim]")
        return

    new_model = parts[1].strip()
    await client.patch_session(state.session_key, model=new_model)
    state.model = new_model
    console.print(f"[green]model:[/green] {new_model}")
