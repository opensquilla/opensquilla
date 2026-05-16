"""Local skill search row loading for CLI skill views."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any


async def search_skill_rows(query: str, *, limit: int = 20) -> list[dict[str, Any]]:
    """Search local skill sources and return JSON-ready rows for CLI rendering."""

    from opensquilla.skills.hub.operations import search_skills, skill_search_request

    outcome = await search_skills(
        None,
        skill_search_request({"query": query, "limit": limit}),
    )
    return [asdict(result) for result in outcome.results]
