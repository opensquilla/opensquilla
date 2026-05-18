"""Community skill search request parsing and runtime operations."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

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


def skill_search_request(params: Mapping[str, Any] | None) -> SkillSearchRequest:
    """Return a search request from RPC params while preserving wire defaults."""

    if not isinstance(params, Mapping) or "query" not in params:
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


def installed_skill_names() -> set[str]:
    """Return installed Community skill aliases."""

    from opensquilla.skills.hub.lockfile import installed_skill_names as _installed_names

    return _installed_names()


def default_skill_router_factory() -> Any | None:
    """Return the default Community skill router."""

    from opensquilla.skills.hub.defaults import get_default_skill_router

    return get_default_skill_router()


async def search_skills(
    router: Any | None,
    request: SkillSearchRequest,
    *,
    default_router_factory: SkillRouterFactory | None = None,
) -> SkillSearchOutcome:
    """Search Community skill sources and include installed-skill aliases."""

    if router is None:
        factory = (
            default_skill_router_factory
            if default_router_factory is None
            else default_router_factory
        )
        router = factory()
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

__all__ = [
    "default_skill_router_factory",
    "installed_skill_names",
    "SkillRouterFactory",
    "SkillSearchOutcome",
    "SkillSearchRequest",
    "search_skills",
    "skill_search_request",
]
