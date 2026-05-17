"""CLI workflows for skill tap commands."""

from __future__ import annotations

from opensquilla.cli.skills_tap_presenters import (
    emit_skill_tap_added,
    emit_skill_tap_error,
    emit_skill_tap_removed,
    emit_skill_taps,
)
from opensquilla.cli.skills_taps import add_skill_tap, list_skill_taps, remove_skill_tap


def add_skill_tap_for_cli(owner_repo: str) -> None:
    """Add a skill tap and emit the CLI result."""

    try:
        tap = add_skill_tap(owner_repo)
    except ValueError as error:
        emit_skill_tap_error(error)
        return

    emit_skill_tap_added(tap)


def list_skill_taps_for_cli() -> None:
    """List skill taps and emit the CLI result."""

    emit_skill_taps(list_skill_taps())


def remove_skill_tap_for_cli(owner_repo: str) -> None:
    """Remove a skill tap and emit the CLI result."""

    emit_skill_tap_removed(owner_repo, removed=remove_skill_tap(owner_repo))
