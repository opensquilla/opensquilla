"""Model and usage slash-command workflows for interactive gateway chat."""

from __future__ import annotations

from typing import Any, Protocol

from opensquilla.cli.repl.session_state import ChatSessionState
from opensquilla.cli.ui import console


class ModelUsageClient(Protocol):
    async def patch_session(self, key: str, **fields: Any) -> dict[str, Any]: ...

    async def usage_status(self) -> dict[str, Any]: ...


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


def handle_cost_command(state: ChatSessionState) -> None:
    """Handle the gateway chat /cost command."""

    console.print(state.usage.render())


async def handle_usage_command(client: ModelUsageClient) -> None:
    """Handle the gateway chat /usage command."""

    payload = await client.usage_status()
    console.print(
        "[dim]aggregate usage: "
        f"{payload.get('totalTokens', 0):,} tok · "
        f"${float(payload.get('totalCostUsd', 0.0) or 0.0):.6f}[/dim]"
    )
