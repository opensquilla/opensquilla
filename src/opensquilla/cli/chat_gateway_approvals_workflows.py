"""Gateway approvals diagnostics slash-command workflow."""

from __future__ import annotations

from typing import Any, cast

from opensquilla.cli.ui import console


async def handle_gateway_approvals_command(
    command: str,
    client: object | None = None,
) -> bool:
    """Handle approval diagnostics and reset commands."""
    parts = command.split()
    arg = parts[1].lower() if len(parts) > 1 else "status"

    if client is None:
        from opensquilla.application.approval_queue import get_approval_queue
        from opensquilla.application.intent_cache import get_intent_cache

        queue = get_approval_queue()
        cache = get_intent_cache()
        if arg == "reset":
            queue.set_settings(mode="prompt")
            cache.clear()
            console.print("[cyan]Approval mode reset to prompt; cache cleared.[/cyan]")
            return True
        entries = [
            f"  [dim]{scope}[/dim] {k}:{t}"
            for (k, t), (_exp, scope) in cache._entries.items()  # noqa: SLF001
        ]
        console.print(f"[cyan]mode:[/cyan] {queue.get_settings().mode}")
        console.print(f"[cyan]cached intents ({len(entries)}):[/cyan]")
        for line in entries or ["  [dim](none)[/dim]"]:
            console.print(line)
        return True

    from opensquilla.cli.gateway_client import GatewayClient

    assert isinstance(client, GatewayClient)

    if arg == "reset":
        try:
            await client.set_approval_mode("prompt")
            await client.forget_approvals()
            console.print("[cyan]Approval mode reset to prompt; server cache cleared.[/cyan]")
        except Exception as exc:
            console.print(f"[red]Failed to reset approvals:[/red] {type(exc).__name__}: {exc}")
            console.print("[red]Restart the gateway if this is an older build.[/red]")
        return True

    try:
        snap = await client.approvals_snapshot()
    except Exception as exc:
        console.print(f"[red]Failed to query approvals:[/red] {type(exc).__name__}: {exc}")
        console.print("[red]Older gateway? Restart it.[/red]")
        return True

    console.print(f"[cyan]mode:[/cyan] {snap.get('mode')}")
    raw_entries = snap.get("intent_cache_entries")
    approval_entries = (
        cast(list[dict[str, Any]], raw_entries) if isinstance(raw_entries, list) else []
    )
    console.print(f"[cyan]cached intents ({len(approval_entries)}):[/cyan]")
    if not approval_entries:
        console.print("  [dim](none)[/dim]")
    for entry in approval_entries:
        console.print(
            f"  [dim]{entry.get('scope')}[/dim] "
            f"{entry.get('kind')}:{entry.get('target')}"
        )
    return True
