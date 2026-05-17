"""Gateway-backed session queries for CLI workflows."""

from __future__ import annotations

from typing import Any, cast

from opensquilla.cli.gateway_rpc import run_gateway_sync


def list_sessions_from_gateway(*, limit: int, json_output: bool) -> dict[str, Any]:
    """Load recent sessions from the running gateway."""

    async def _run(client: Any) -> dict[str, Any]:
        return cast(dict[str, Any], await client.list_sessions(limit=limit))

    return cast(dict[str, Any], run_gateway_sync(_run, json_output=json_output))
