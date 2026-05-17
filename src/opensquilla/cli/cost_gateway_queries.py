"""Gateway-backed usage/cost queries for CLI workflows."""

from __future__ import annotations

from typing import Any, cast

from opensquilla.cli.gateway_rpc import run_gateway_sync


def load_usage_cost_from_gateway(*, json_output: bool) -> dict[str, Any]:
    """Load aggregate usage/cost data from the running gateway."""

    async def _with_client(client: Any) -> dict[str, Any]:
        return cast(dict[str, Any], await client.usage_cost())

    return cast(
        dict[str, Any],
        run_gateway_sync(_with_client, json_output=json_output),
    )
