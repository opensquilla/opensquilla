from __future__ import annotations

from types import SimpleNamespace

import pytest

from opensquilla.skills.hub import search as hub_search
from opensquilla.skills.hub.search import search_skills, skill_search_request


def test_skill_search_request_validates_defaults_and_source_filter() -> None:
    request = skill_search_request({"query": "plan"})

    assert request.query == "plan"
    assert request.limit == 20
    assert request.source_id is None

    capped = skill_search_request({"query": "plan", "limit": "150", "source": "github"})
    assert capped.limit == 100
    assert capped.source_id == "github"

    fallback = skill_search_request({"query": "plan", "limit": "many", "source": 123})
    assert fallback.limit == 20
    assert fallback.source_id is None

    with pytest.raises(ValueError, match="params.query is required"):
        skill_search_request(None)
    with pytest.raises(ValueError, match="params.query is required"):
        skill_search_request({})


@pytest.mark.asyncio
async def test_search_skills_returns_unavailable_without_any_router() -> None:
    outcome = await search_skills(
        None,
        skill_search_request({"query": "plan"}),
        default_router_factory=lambda: None,
    )

    assert outcome.results == []
    assert outcome.installed_names == set()
    assert outcome.unavailable is True


@pytest.mark.asyncio
async def test_search_skills_delegates_to_router_and_reads_installed_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeRouter:
        async def search(
            self,
            query: object,
            *,
            limit: int,
            source_id: str | None,
        ) -> list[SimpleNamespace]:
            assert query == "plan"
            assert limit == 3
            assert source_id == "github"
            return [SimpleNamespace(identifier="planner")]

    monkeypatch.setattr(hub_search, "installed_skill_names", lambda: {"planner"})

    outcome = await search_skills(
        FakeRouter(),
        skill_search_request({"query": "plan", "limit": 3, "source": "github"}),
    )

    assert [result.identifier for result in outcome.results] == ["planner"]
    assert outcome.installed_names == {"planner"}
    assert outcome.unavailable is False


@pytest.mark.asyncio
async def test_search_skills_uses_default_router_when_context_router_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeRouter:
        async def search(
            self,
            query: object,
            *,
            limit: int,
            source_id: str | None,
        ) -> list[SimpleNamespace]:
            assert query == "plan"
            assert limit == 20
            assert source_id is None
            return [SimpleNamespace(identifier="planner")]

    monkeypatch.setattr(hub_search, "installed_skill_names", lambda: {"planner"})

    outcome = await search_skills(
        None,
        skill_search_request({"query": "plan"}),
        default_router_factory=FakeRouter,
    )

    assert [result.identifier for result in outcome.results] == ["planner"]
    assert outcome.installed_names == {"planner"}
    assert outcome.unavailable is False
