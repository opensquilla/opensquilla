"""Standalone chat durable transcript rewrite guards."""

from __future__ import annotations

import inspect
from typing import Any

from opensquilla.cli.ui import console


async def read_standalone_transcript(
    session_manager: Any,
    session_key: str,
) -> list[Any] | None:
    """Read the durable transcript before a destructive standalone command."""
    if session_manager is None:
        return []
    for method_name in ("get_transcript", "read_transcript"):
        reader = getattr(session_manager, method_name, None)
        if not callable(reader):
            continue
        try:
            result = reader(session_key)
            if inspect.isawaitable(result):
                result = await result
        except KeyError:
            return []
        except Exception:  # noqa: BLE001
            return None
        return list(result or [])
    return None


async def flush_before_standalone_rewrite(
    svc: Any,
    session_key: str,
    *,
    operation: str,
) -> bool:
    """Fail closed before reset/compact when a durable transcript exists."""
    transcript = await read_standalone_transcript(
        getattr(svc, "session_manager", None),
        session_key,
    )
    if transcript is None:
        console.print(
            f"[yellow]{operation} aborted: could not inspect the durable transcript.[/yellow]"
        )
        return False
    if not transcript:
        return True

    flush_service = getattr(svc, "flush_service", None)
    if flush_service is None:
        console.print(
            f"[yellow]{operation} aborted: flush service is unavailable and "
            "the durable transcript is non-empty.[/yellow]"
        )
        return False

    try:
        receipt = await flush_service.execute(
            transcript,
            session_key,
            agent_id="main",
            timeout=30.0,
            message_window=0,
            segment_mode="auto",
        )
    except Exception as exc:  # noqa: BLE001
        console.print(f"[yellow]{operation} aborted: flush failed ({exc}).[/yellow]")
        return False

    if getattr(receipt, "mode", None) == "error":
        error = getattr(receipt, "error", None) or "unknown error"
        console.print(f"[yellow]{operation} aborted: flush failed ({error}).[/yellow]")
        return False
    return True
