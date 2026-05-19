"""CLI workflows for reset commands."""

from __future__ import annotations

import asyncio
from typing import Any

from opensquilla.cli.gateway_client import GatewayClient, GatewayRPCError
from opensquilla.cli.reset_presenters import emit_reset_error_exit, emit_reset_success
from opensquilla.cli.url_utils import normalize_gateway_url


def reset_session_for_cli(key: str, *, gateway_url: str) -> None:
    """Reset a session through the gateway and emit the CLI result."""

    try:
        payload = asyncio.run(_reset_session(key, gateway_url=gateway_url))
    except GatewayRPCError as exc:
        emit_reset_error_exit(exc)
        return
    emit_reset_success(payload)


async def _reset_session(key: str, *, gateway_url: str) -> dict[str, Any]:
    client = GatewayClient()
    try:
        await client.connect(normalize_gateway_url(gateway_url))
        return await client.reset_session(key)
    finally:
        await client.close()
