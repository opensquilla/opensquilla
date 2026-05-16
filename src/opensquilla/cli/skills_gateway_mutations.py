"""Gateway-backed skill mutation helpers for CLI skill commands."""

from __future__ import annotations

from typing import Any

import typer

from opensquilla.cli.gateway_rpc import default_gateway_url, rpc_error_exit_code
from opensquilla.cli.output import emit_error


async def try_gateway_skill_mutation(
    method: str,
    params: dict[str, Any],
    *,
    json_output: bool,
) -> dict[str, Any] | None:
    """Use the running gateway when available; return None only for connect failures."""

    from opensquilla.cli import gateway_client as gateway_client_module

    client = gateway_client_module.GatewayClient()
    try:
        await client.connect(default_gateway_url())
    except (SystemExit, ConnectionError, OSError):
        await client.close()
        return None

    try:
        payload = await client.call(method, params)
    except gateway_client_module.GatewayRPCError as exc:
        emit_error(
            exc.message,
            json_output=json_output,
            code=exc.code,
            details=exc.data,
        )
        raise typer.Exit(rpc_error_exit_code(exc.code)) from exc
    except (ConnectionError, OSError) as exc:
        emit_error(str(exc), json_output=json_output, code="GATEWAY_UNAVAILABLE")
        raise typer.Exit(1) from exc
    finally:
        await client.close()

    return payload if isinstance(payload, dict) else {"result": payload}
