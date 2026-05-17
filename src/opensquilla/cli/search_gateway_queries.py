"""Gateway-backed search queries for CLI workflows."""

from __future__ import annotations

from typing import Any, cast

from opensquilla.cli.gateway_rpc import run_gateway_sync


def load_search_status(
    provider: str | None,
    *,
    json_output: bool,
) -> dict[str, Any]:
    """Load runtime search provider diagnostics from the gateway."""

    async def _run(client: Any) -> dict[str, Any]:
        params: dict[str, object] = {}
        if provider:
            params["provider"] = provider
        payload = await client.call("search.status", params)
        assert isinstance(payload, dict)
        return payload

    return cast(dict[str, Any], run_gateway_sync(_run, json_output=json_output))


def run_search_query(
    query: str,
    *,
    provider: str | None,
    limit: int | None,
    json_output: bool,
) -> dict[str, Any]:
    """Run a diagnostic search query through the gateway."""

    async def _run(client: Any) -> dict[str, Any]:
        params: dict[str, object] = {"query": query}
        if provider:
            params["provider"] = provider
        if limit is not None:
            params["limit"] = limit
        payload = await client.call("search.query", params)
        assert isinstance(payload, dict)
        return payload

    return cast(dict[str, Any], run_gateway_sync(_run, json_output=json_output))
