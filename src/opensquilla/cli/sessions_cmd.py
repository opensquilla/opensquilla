"""Sessions command — list/show/resume/delete/export sessions."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

import typer

from opensquilla.cli.gateway_rpc import run_gateway_sync
from opensquilla.cli.output import print_json
from opensquilla.cli.repl.session_state import messages_to_markdown
from opensquilla.cli.sessions_workflows import (
    list_sessions_for_cli,
    show_session_for_cli,
)
from opensquilla.cli.ui import console, error_panel
from opensquilla.cli.url_utils import normalize_gateway_url

app = typer.Typer(help="Manage chat sessions.")

_CLIENT_UNAVAILABLE = object()
_ACTION_FAILED = object()


def _resolved_key(payload: dict[str, Any], fallback: str) -> str:
    value = payload.get("session_key") or payload.get("key") or fallback
    return str(value)


async def _with_client(action):
    from opensquilla.cli.gateway_client import GatewayClient, GatewayRPCError

    client = GatewayClient()
    try:
        await client.connect(
            normalize_gateway_url(os.environ.get("OPENSQUILLA_GATEWAY_URL", "ws://localhost:18790/ws"))
        )
        return await action(client)
    except SystemExit as exc:
        console.print(f"[dim]{exc}[/dim]")
        return _CLIENT_UNAVAILABLE
    except GatewayRPCError as exc:
        console.print(error_panel(str(exc)))
        return _ACTION_FAILED
    finally:
        await client.close()


@app.command("list")
def sessions_list(
    limit: int = typer.Option(50, "--limit", "-n", help="Maximum rows"),
    agent: str | None = typer.Option(None, "--agent", help="Filter by agent id"),
    status: str | None = typer.Option(None, "--status", help="Filter by session status"),
    channel: str | None = typer.Option(None, "--channel", help="Filter by channel/source"),
    since: str | None = typer.Option(None, "--since", help="ISO date/datetime or epoch timestamp"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """List recent sessions."""
    list_sessions_for_cli(
        limit=limit,
        agent=agent,
        status=status,
        channel=channel,
        since=since,
        json_output=json_output,
    )


@app.command("show")
def sessions_show(
    session_id: str = typer.Argument(..., help="Session ID to inspect"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Show details of a specific session."""
    show_session_for_cli(session_id, json_output=json_output)


@app.command("resume")
def sessions_resume(session_id: str = typer.Argument(..., help="Session ID to resume")) -> None:
    """Resume a session in interactive chat."""
    from opensquilla.cli.chat_cmd import run_chat

    async def _run(client):
        return await client.resolve_session(session_id)

    result = asyncio.run(_with_client(_run))
    if result is _CLIENT_UNAVAILABLE:
        console.print(f"[dim]Session {session_id!r} requires a running gateway.[/dim]")
        return
    if result is _ACTION_FAILED:
        return
    run_chat(session_id=_resolved_key(result, session_id))


@app.command("abort")
def sessions_abort(
    session_id: str = typer.Argument(..., help="Session ID to abort"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Abort a running session turn."""

    async def _run(client):
        resolved = await client.resolve_session(session_id)
        key = _resolved_key(resolved, session_id)
        result = await client.abort_session(key)
        if isinstance(result, dict):
            return {"resolved": resolved, **result}
        return {"resolved": resolved, "result": result}

    payload = run_gateway_sync(_run, json_output=json_output)
    if json_output:
        print_json(payload)
        return
    key = payload.get("key") or session_id
    aborted = bool(payload.get("aborted", False))
    console.print(f"{'Aborted' if aborted else 'No running task for'} session {key!r}")


@app.command("delete")
def sessions_delete(
    session_id: str = typer.Argument(..., help="Session ID to delete"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Delete a session."""
    if not yes:
        confirmed = typer.confirm(f"Delete session {session_id!r}?")
        if not confirmed:
            raise typer.Abort()

    async def _run(client):
        resolved = await client.resolve_session(session_id)
        key = _resolved_key(resolved, session_id)
        return await client.delete_sessions([key])

    result = asyncio.run(_with_client(_run))
    if result is _CLIENT_UNAVAILABLE:
        console.print("[dim]Session deletion requires a running gateway.[/dim]")
        return
    if result is _ACTION_FAILED:
        return
    console.print_json(data=result)


@app.command("export")
def sessions_export(
    session_id: str = typer.Argument(..., help="Session ID to export"),
    output: Path | None = typer.Option(None, "--output", "-o", help="Output file"),
    format: str = typer.Option("md", "--format", help="Export format: md|json"),
) -> None:
    """Export session transcript and metadata.

    Uses the existing chat.history RPC for persisted transcript messages and
    falls back to session preview when no messages are available.
    """
    if format not in {"md", "json"}:
        console.print("[red]--format must be md or json[/red]")
        raise typer.Exit(2)

    async def _run(client):
        resolved = await client.resolve_session(session_id)
        key = _resolved_key(resolved, session_id)
        preview = await client.preview_sessions(keys=[key])
        history = await client.session_history(key, limit=1000)
        return {"resolved": resolved, "preview": preview, "history": history}

    result: dict[str, Any] | None = asyncio.run(_with_client(_run))
    if result is _CLIENT_UNAVAILABLE:
        console.print("[dim]Session export requires a running gateway.[/dim]")
        return
    if result is _ACTION_FAILED:
        return
    if result is None:
        console.print("[red]Session export returned no data.[/red]")
        return
    target = output or Path(f"{session_id.replace(':', '-')}.{format}")
    if format == "json":
        target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        resolved = result.get("resolved", {})
        key = _resolved_key(resolved, session_id)
        previews = result.get("preview", {}).get("previews", [])
        preview = previews[0] if previews else {}
        messages = result.get("history", {}).get("messages", [])
        transcript = messages_to_markdown(messages) if isinstance(messages, list) else ""
        if not transcript.strip():
            transcript = f"## Preview\n\n{preview.get('lastMessage', '')}\n"
        body = (
            f"# Session {key}\n\n"
            f"- Status: {resolved.get('status', '')}\n"
            f"- Model: {resolved.get('model') or ''}\n"
            f"- Updated: {resolved.get('updated_at', '')}\n\n"
            f"{transcript}"
        )
        target.write_text(body, encoding="utf-8")
    console.print(f"[green]Exported:[/green] {target}")
