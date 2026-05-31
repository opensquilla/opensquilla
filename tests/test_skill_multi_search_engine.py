"""multi-search-engine skill — load + missing-key engines fail soft."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from opensquilla.skills.eligibility import EligibilityContext, check_eligibility
from opensquilla.skills.loader import SkillLoader

ROOT = Path(__file__).resolve().parents[1]
BUNDLED = ROOT / "src" / "opensquilla" / "skills" / "bundled"
SCRIPTS = BUNDLED / "multi-search-engine" / "scripts"


def _spec() -> object:
    return SkillLoader(bundled_dir=BUNDLED).get_by_name("multi-search-engine")


def test_skill_loads() -> None:
    spec = _spec()
    assert spec is not None
    assert spec.name == "multi-search-engine"


def test_eligibility_with_python(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "opensquilla.skills.eligibility.shutil.which",
        lambda name: "/usr/bin/python3" if name in {"python", "python3"} else None,
    )
    spec = _spec()
    assert spec is not None
    assert check_eligibility(spec, EligibilityContext.auto())


def test_brave_without_key_fails_soft(monkeypatch: pytest.MonkeyPatch) -> None:
    """Engine missing its API key must not crash the run; record an error and continue."""
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    sys.path.insert(0, str(SCRIPTS))
    try:
        import search  # type: ignore[import-not-found]
    finally:
        sys.path.pop(0)

    payload = search.search_all(
        query="anything",
        engines=["brave"],
        limit=3,
        strict=False,
    )
    assert payload["query"] == "anything"
    assert payload["results"] == []
    assert any("BRAVE_SEARCH_API_KEY/BRAVE_API_KEY" in e["reason"] for e in payload["errors"])


def test_brave_accepts_current_search_env_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """OpenSquilla config uses BRAVE_SEARCH_API_KEY; the skill must honor it."""
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "brave-current")
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    sys.path.insert(0, str(SCRIPTS))
    try:
        import search  # type: ignore[import-not-found]
    finally:
        sys.path.pop(0)

    captured: dict[str, object] = {}

    class _Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "web": {
                    "results": [
                        {
                            "title": "Example",
                            "url": "https://example.com",
                            "description": "Snippet",
                        },
                    ],
                },
            }

    class _Client:
        def __enter__(self) -> _Client:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def get(self, url: str, *, params: dict[str, object], headers: dict[str, str]) -> _Response:
            captured["headers"] = headers
            captured["params"] = params
            return _Response()

    monkeypatch.setattr(search, "_client", lambda: _Client())

    payload = search.search_all(
        query="anything",
        engines=["brave"],
        limit=1,
        strict=False,
    )

    assert payload["errors"] == []
    assert payload["results"][0]["url"] == "https://example.com"
    assert captured["headers"]["X-Subscription-Token"] == "brave-current"


def test_search_query_contract_extracts_planner_query(monkeypatch: pytest.MonkeyPatch) -> None:
    """Meta report planners may pass SEARCH_QUERY plus preferences; engines get only the query."""
    sys.path.insert(0, str(SCRIPTS))
    try:
        import search  # type: ignore[import-not-found]
    finally:
        sys.path.pop(0)

    captured: dict[str, object] = {}

    def fake_engine(query: str, limit: int) -> list[object]:
        captured["query"] = query
        captured["limit"] = limit
        return []

    monkeypatch.setitem(search.ENGINES, "fake", fake_engine)
    payload = search.search_all(
        query=(
            "SEARCH_QUERY: local-first AI coding assistants 2026 pros cons\n"
            "AUDIENCE: CTO\n"
            "REPORT_TYPE: technical"
        ),
        engines=["fake"],
        limit=7,
        strict=False,
    )

    assert payload["query"] == "local-first AI coding assistants 2026 pros cons"
    assert captured == {
        "query": "local-first AI coding assistants 2026 pros cons",
        "limit": 7,
    }


def test_unknown_engine_recorded() -> None:
    sys.path.insert(0, str(SCRIPTS))
    try:
        import search  # type: ignore[import-not-found]
    finally:
        sys.path.pop(0)

    payload = search.search_all(
        query="x",
        engines=["bogus-engine-name"],
        limit=1,
        strict=False,
    )
    assert payload["results"] == []
    assert any("unknown engine" in e["reason"] for e in payload["errors"])
