"""Presentation helpers for CLI skill publish commands."""

from __future__ import annotations

from typing import Any

from opensquilla.cli.ui import console


def emit_skill_publish_result(result: Any) -> None:
    """Emit a skill publish result."""

    if result.success:
        console.print(f"[green]OK:[/] {result.message}")
    else:
        console.print(f"[red]Failed:[/] {result.message}")
