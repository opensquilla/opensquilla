"""CLI workflows for durable memory RPC commands."""

from __future__ import annotations

from typing import Any, cast

from opensquilla.cli.gateway_rpc import run_gateway_sync
from opensquilla.cli.memory_presenters import (
    emit_memory_search_results,
    emit_memory_source_content,
    emit_memory_sources,
    emit_memory_status,
)


def show_memory_status_for_cli(agent_id: str, *, json_output: bool) -> None:
    """Load and emit memory backend status."""

    payload = _call_memory_rpc(
        "doctor.memory.status",
        {"agentId": agent_id},
        json_output=json_output,
    )
    emit_memory_status(payload, agent_id=agent_id, json_output=json_output)


def list_memory_sources_for_cli(agent_id: str, *, json_output: bool) -> None:
    """Load and emit durable memory source files."""

    payload = _call_memory_rpc(
        "memory.list",
        {"agentId": agent_id},
        json_output=json_output,
    )
    emit_memory_sources(payload, agent_id=agent_id, json_output=json_output)


def search_memory_sources_for_cli(
    query: str,
    *,
    agent_id: str,
    limit: int,
    json_output: bool,
) -> None:
    """Search and emit durable memory results."""

    payload = _call_memory_rpc(
        "memory.search",
        {"query": query, "agentId": agent_id, "limit": limit},
        json_output=json_output,
    )
    emit_memory_search_results(payload, agent_id=agent_id, json_output=json_output)


def show_memory_source_for_cli(
    path: str,
    *,
    agent_id: str,
    from_line: int | None,
    lines: int | None,
    json_output: bool,
) -> None:
    """Load and emit one durable memory source."""

    params: dict[str, object] = {"path": path, "agentId": agent_id}
    if from_line is not None:
        params["fromLine"] = from_line
    if lines is not None:
        params["lines"] = lines

    payload = _call_memory_rpc("memory.show", params, json_output=json_output)
    emit_memory_source_content(payload, json_output=json_output)


def _call_memory_rpc(
    method: str,
    params: dict[str, object],
    *,
    json_output: bool,
) -> dict[str, Any]:
    async def _run(client: Any) -> Any:
        return await client.call(method, params)

    return cast(dict[str, Any], run_gateway_sync(_run, json_output=json_output))
