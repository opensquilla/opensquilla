"""Local tap operations for CLI skill commands."""

from __future__ import annotations

from typing import Any


def add_skill_tap(owner_repo: str) -> Any:
    """Add a custom skill tap using the local tap manager."""

    from opensquilla.skills.hub.operations import (
        add_tap,
        default_taps_manager_factory,
        tap_add_request,
    )

    manager = default_taps_manager_factory()
    return add_tap(manager, tap_add_request({"owner_repo": owner_repo}))


def list_skill_taps() -> list[Any]:
    """List custom skill taps using the local tap manager."""

    from opensquilla.skills.hub.operations import (
        default_taps_manager_factory,
        list_taps,
    )

    manager = default_taps_manager_factory()
    return list_taps(manager)


def remove_skill_tap(owner_repo: str) -> bool:
    """Remove a custom skill tap using the local tap manager."""

    from opensquilla.skills.hub.operations import (
        default_taps_manager_factory,
        remove_tap,
        tap_remove_request,
    )

    manager = default_taps_manager_factory()
    return remove_tap(manager, tap_remove_request({"owner_repo": owner_repo}))
