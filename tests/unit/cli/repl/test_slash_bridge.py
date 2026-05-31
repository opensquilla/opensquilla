from __future__ import annotations

from typing import Any, cast

import pytest
from rich.console import Console
from rich.panel import Panel

from opensquilla.cli.repl.session_state import ChatSessionState
from opensquilla.cli.repl.stream import TurnResult


@pytest.mark.asyncio
async def test_gateway_slash_bridge_syncs_io_and_builds_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.cli.repl import slash_adapter, slash_bridge
    from opensquilla.cli.repl.slash_adapter import GatewaySlashContext

    output_console = Console(file=None, force_terminal=False)
    observed: dict[str, Any] = {}

    async def fake_handle(cmd: str, context: GatewaySlashContext) -> bool:
        observed["cmd"] = cmd
        observed["context"] = context
        observed["adapter_console"] = slash_adapter.console
        observed["adapter_error_panel"] = slash_adapter.error_panel
        return True

    async def fake_stream(*args: Any, **kwargs: Any) -> TurnResult:
        return TurnResult(text="streamed")

    def fake_error_panel(message: str, *, title: str = "Error") -> Panel:
        return Panel(message, title=title)

    monkeypatch.setattr(slash_adapter, "handle_gateway_slash_command", fake_handle)

    state = ChatSessionState(session_key="agent:main:test", model="openai/test")
    client = cast(slash_bridge.GatewayClientLike, object())
    elevated_state: dict[str, str | None] = {"mode": "enabled"}

    handled = await slash_bridge.handle_gateway_slash_command(
        "/status",
        state,
        client,
        elevated_state,
        stream_response=fake_stream,
        output_console=output_console,
        error_panel_factory=fake_error_panel,
    )

    context = observed["context"]
    assert handled is True
    assert observed["cmd"] == "/status"
    assert context.state is state
    assert context.client is client
    assert context.elevated_state is elevated_state
    assert context.stream_response is fake_stream
    assert observed["adapter_console"] is output_console
    assert observed["adapter_error_panel"] is fake_error_panel
