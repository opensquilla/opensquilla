"""Standalone helpers for chat approval prompts and decisions."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from rich.panel import Panel

from opensquilla.cli.repl.prompt import prompt_approval
from opensquilla.cli.ui import console


async def maybe_handle_approval(
    result: Any,
    live: Any,
    resolver: Callable[..., Awaitable[Any]],
    elevated_state: dict[str, str | None] | None = None,
) -> None:
    """Prompt for approval when *result* carries an approval envelope."""
    payload: dict[str, Any]
    if isinstance(result, str):
        try:
            parsed = json.loads(result)
        except (ValueError, TypeError):
            return
        if not isinstance(parsed, dict):
            return
        payload = parsed
    elif isinstance(result, dict):
        payload = result
    else:
        return

    if payload.get("status") == "blocked":
        live.stop()
        try:
            console.print()
            console.print(
                Panel(
                    f"[bold]Command:[/bold] {str(payload.get('command', '')).strip()}\n"
                    f"[dim]{payload.get('message', '')}[/dim]",
                    title="[red]Blocked (sensitive path)[/red]",
                    border_style="red",
                )
            )
        finally:
            live.start()
        return

    status = str(payload.get("status") or "")
    if status not in {"approval_required", "approval_pending"}:
        return
    approval_id = payload.get("approval_id")
    if not isinstance(approval_id, str) or not approval_id:
        return
    command = str(payload.get("command", "")).strip()
    warning = str(payload.get("warning") or payload.get("message") or "").strip()

    live.stop()
    try:
        console.print()
        body = f"[bold]Command:[/bold] {command or '(not shown)'}"
        if warning:
            body += f"\n[dim]{warning}[/dim]"
        console.print(
            Panel(
                body,
                title=(
                    "[yellow]Approval pending[/yellow]"
                    if status == "approval_pending"
                    else "[yellow]Approval required[/yellow]"
                ),
                border_style="yellow",
            )
        )
        console.print(
            "[dim]  [bold]o[/bold]nce    allow this call only[/dim]\n"
            "[dim]  [bold]a[/bold]lways  allow this intent for the session[/dim]\n"
            "[dim]  [bold]b[/bold]ypass  approve + skip future approvals "
            "(sensitive paths still blocked)[/dim]\n"
            "[dim]  [bold]d[/bold]eny    reject[/dim]"
        )
        answer = await prompt_approval("Decision [o/a/b/d]: ")

        flip_to_bypass = False
        if answer in ("b", "bypass"):
            approved, allow_always, label = True, True, "Approved + bypass mode"
            flip_to_bypass = True
        elif answer in ("a", "always"):
            approved, allow_always, label = True, True, "Always approved"
        elif answer in ("o", "y", "yes", "once", ""):
            approved, allow_always, label = True, False, "Approved (once)"
        else:
            approved, allow_always, label = False, False, "Denied"

        try:
            await resolver(approval_id, approved, allow_always=allow_always)
            color = "green" if approved else "red"
            if flip_to_bypass:
                if elevated_state is not None:
                    elevated_state["mode"] = "bypass"
                suffix = (
                    " — session now in [red]bypass[/red] mode. "
                    "Sensitive paths still blocked. Use /elevated off to revert."
                )
            elif allow_always:
                suffix = " — future similar intents auto-approve."
            else:
                suffix = ""
            console.print(f"[{color}]{label}[/{color}]{suffix}")
        except Exception as exc:  # pragma: no cover - transport/queue errors
            console.print(f"[red]Failed to resolve approval:[/red] {exc}")
    finally:
        live.start()


def local_approval_resolver() -> Callable[..., Awaitable[None]]:
    """Return a resolver that talks directly to the in-process approval queue."""

    async def _resolve(approval_id: str, approved: bool, *, allow_always: bool = False) -> None:
        from opensquilla.application.approval_queue import get_approval_queue

        get_approval_queue().resolve(approval_id, approved, allow_always=allow_always)

    return _resolve
