"""Local skill row loading for CLI skill views."""

from __future__ import annotations

from typing import Any

from opensquilla.skills.runtime_facade import load_configured_skill_rows


def load_skill_rows() -> list[dict[str, Any]]:
    """Load local skill rows for the CLI list view."""

    return load_configured_skill_rows()
