"""Gateway-backed channel queries for CLI workflows."""

from __future__ import annotations

from typing import Any, cast

from opensquilla.cli.gateway_rpc import run_gateway_sync


def load_channel_status(*, json_output: bool) -> dict[str, Any]:
    """Load runtime channel status from the gateway."""

    async def _run(client):
        return await client.call("channels.status", {})

    return cast(dict[str, Any], run_gateway_sync(_run, json_output=json_output))


def restart_channel(name: str, *, json_output: bool) -> dict[str, Any]:
    """Restart a live messaging channel through the gateway."""

    async def _run(client):
        return await client.call("channels.restart", {"name": name})

    return cast(dict[str, Any], run_gateway_sync(_run, json_output=json_output))


def logout_channel(name: str, *, json_output: bool) -> dict[str, Any]:
    """Log out a live messaging channel through the gateway."""

    async def _run(client):
        return await client.call("channels.logout", {"name": name})

    return cast(dict[str, Any], run_gateway_sync(_run, json_output=json_output))
