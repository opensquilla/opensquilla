"""Gateway-backed session queries for CLI workflows."""

from __future__ import annotations

from typing import Any, cast

from opensquilla.cli.gateway_rpc import run_gateway_sync


def list_sessions_from_gateway(*, limit: int, json_output: bool) -> dict[str, Any]:
    """Load recent sessions from the running gateway."""

    async def _run(client: Any) -> dict[str, Any]:
        return cast(dict[str, Any], await client.list_sessions(limit=limit))

    return cast(dict[str, Any], run_gateway_sync(_run, json_output=json_output))


def _resolved_key(payload: dict[str, Any], fallback: str) -> str:
    value = payload.get("session_key") or payload.get("key") or fallback
    return str(value)


def load_session_preview_from_gateway(
    session_id: str,
    *,
    json_output: bool,
) -> dict[str, Any]:
    """Load resolved session metadata and preview from the running gateway."""

    async def _run(client: Any) -> dict[str, Any]:
        resolved = cast(dict[str, Any], await client.resolve_session(session_id))
        preview = cast(
            dict[str, Any],
            await client.preview_sessions(keys=[_resolved_key(resolved, session_id)]),
        )
        return {"resolved": resolved, "preview": preview}

    return cast(dict[str, Any], run_gateway_sync(_run, json_output=json_output))
