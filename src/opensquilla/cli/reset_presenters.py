"""CLI presenters for reset command output."""

from __future__ import annotations

from typing import Any

import typer


def emit_reset_error_exit(exc: Any) -> None:
    """Emit a reset RPC failure and exit with the preserved CLI status."""

    data = exc.data or {}
    receipt = data.get("flush_receipt", {}) or {}
    typer.secho(f"\u2717 Reset aborted: {exc.message}", fg=typer.colors.RED)
    typer.echo(f"  Session preserved: {data.get('session_id', '?')}")
    if receipt.get("error"):
        typer.echo(f"  Cause: {receipt['error']}")
    raise typer.Exit(1)


def emit_reset_success(payload: dict[str, Any]) -> None:
    """Emit a successful reset receipt."""

    receipt = payload.get("flush_receipt") or {}
    mode = receipt.get("mode", "?")
    typer.secho(
        f"\u2713 Session reset ({payload.get('previous_session_id', '?')} \u2192 "
        f"{payload.get('session_id', '?')}).",
        fg=typer.colors.GREEN,
    )
    if mode == "llm":
        dur = receipt.get("duration_ms", 0) / 1000
        typer.echo(f"  Flush mode: llm ({dur:.1f}s)")
        for p in receipt.get("flushed_paths") or []:
            typer.echo(f"  Saved to: {p}")
    elif mode == "raw":
        reason = receipt.get("raw_reason", "unknown")
        dur = receipt.get("duration_ms", 0) / 1000
        typer.echo(f"  Flush mode: raw (reason: {reason}, after {dur:.1f}s)")
        for p in receipt.get("flushed_paths") or []:
            typer.echo(f"  Saved to: {p} (raw transcript dump)")
    elif mode == "skipped":
        typer.echo("  Flush mode: skipped (empty transcript)")
    else:
        typer.echo(f"  Flush mode: {mode}")
