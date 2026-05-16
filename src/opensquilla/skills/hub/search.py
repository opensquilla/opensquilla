"""Search request handling for Community skill sources."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from opensquilla.skills.hub.defaults import get_default_skill_router
from opensquilla.skills.hub.lockfile import installed_skill_names

SkillRouterFactory = Callable[[], Any | None]


@dataclass(frozen=True)
class SkillSearchRequest:
    """Validated request to search Community skill sources."""

    query: Any
    limit: int
    source_id: str | None


@dataclass(frozen=True)
class SkillSearchOutcome:
    """Result of running a Community skill source search."""

    results: list[Any]
    installed_names: set[str]
    unavailable: bool = False


def skill_search_request(params: dict[str, Any] | None) -> SkillSearchRequest:
    """Return a search request from RPC params while preserving wire defaults."""

    if not isinstance(params, dict) or "query" not in params:
        raise ValueError("params.query is required")

    try:
        limit = min(int(params.get("limit", 20)), 100)
    except (TypeError, ValueError):
        limit = 20

    source_id = params.get("source")
    if source_id is not None and not isinstance(source_id, str):
        source_id = None

    return SkillSearchRequest(
        query=params["query"],
        limit=limit,
        source_id=source_id,
    )


async def search_skills(
    router: Any | None,
    request: SkillSearchRequest,
    *,
    default_router_factory: SkillRouterFactory = get_default_skill_router,
) -> SkillSearchOutcome:
    """Search Community skill sources and include installed-skill aliases."""

    if router is None:
        router = default_router_factory()
    if router is None:
        return SkillSearchOutcome(results=[], installed_names=set(), unavailable=True)

    return SkillSearchOutcome(
        results=await router.search(
            request.query,
            limit=request.limit,
            source_id=request.source_id,
        ),
        installed_names=installed_skill_names(),
    )
