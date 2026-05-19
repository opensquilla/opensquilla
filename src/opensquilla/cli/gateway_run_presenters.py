"""Presentation helpers for ``opensquilla gateway run``."""

from __future__ import annotations

from typing import Any

from opensquilla.cli.ui import console
from opensquilla.gateway.config import is_public_bind
from opensquilla.paths import default_opensquilla_home


def gateway_startup_guidance(host: str, port: int) -> tuple[str, ...]:
    """Return operator-facing guidance shown after the gateway starts."""

    base_url = f"http://{host}:{port}"
    return (
        f"[bold]Web UI:[/bold] {base_url}/control/",
        f"[bold]API base:[/bold] {base_url}",
        f"[bold]Debug log:[/bold] {default_opensquilla_home() / 'logs' / 'debug.log'}",
        "[dim]Keep this terminal open. Press Ctrl+C to stop.[/dim]",
    )


def render_gateway_startup(*, host: str, port: int, config: Any) -> None:
    """Render the startup banner and public-bind warnings."""

    banner_host = f"[red]{host}[/red]" if is_public_bind(host) else f"[cyan]{host}[/cyan]"
    console.print(f"[bold green]Starting OpenSquilla gateway[/bold green] on {banner_host}:{port}")
    for line in gateway_startup_guidance(host, port):
        console.print(line)
    if not is_public_bind(host):
        return

    # Use ASCII-only glyphs here so the warning still prints on Windows
    # consoles configured for legacy GBK code pages (where U+26A0 / em-dash
    # crash Rich's legacy renderer with UnicodeEncodeError).
    console.print(
        "[yellow]WARNING: gateway is bound to a wildcard address - "
        "reachable from every interface.[/yellow]"
    )
    if getattr(getattr(config, "auth", None), "mode", None) == "none":
        console.print(
            "[yellow]  auth.mode=none + wildcard bind = LAN-open. "
            "Anyone reachable on this network can use the chat, sessions, "
            "and config surfaces with your provider credentials.[/yellow]"
        )
    console.print(
        "[yellow]  Bypass / elevated mode remains owner-only and "
        "is unreachable from non-loopback peers; the chat UI will "
        "self-disable that pill.[/yellow]"
    )


def render_gateway_stopped() -> None:
    """Render the Ctrl+C stopped message."""

    console.print("\n[yellow]Gateway stopped.[/yellow]")
