"""Presentation helpers for CLI skill tap commands."""

from __future__ import annotations

from typing import Any

from opensquilla.cli.ui import console


def emit_skill_tap_added(tap: Any) -> None:
    """Emit the result of adding a skill tap."""

    console.print(f"[green]Added tap:[/] {tap.full_name} ({tap.url})")


def emit_skill_tap_error(error: ValueError) -> None:
    """Emit a skill tap validation error."""

    console.print(f"[red]Error:[/] {error}")


def emit_skill_taps(taps: list[Any]) -> None:
    """Emit registered skill taps."""

    if not taps:
        console.print("[dim]No taps registered.[/]")
        return
    for tap in taps:
        console.print(f"  {tap.full_name}  {tap.url}  (added {tap.added_at})")


def emit_skill_tap_removed(owner_repo: str, *, removed: bool) -> None:
    """Emit the result of removing a skill tap."""

    if removed:
        console.print(f"[green]Removed:[/] {owner_repo}")
    else:
        console.print(f"[yellow]Not found:[/] {owner_repo}")
