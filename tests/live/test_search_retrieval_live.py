"""Opt-in live canonical web search smoke tests.

These tests use public, synthetic prompts only and skip unless explicitly enabled
with local credentials.
"""

from __future__ import annotations

import os
from typing import Any, cast

import pytest

from opensquilla.search.canonical import run_canonical_web_search
from opensquilla.search.types import SearchOptions

pytestmark = pytest.mark.live_search


def _require_live_search() -> None:
    if os.environ.get("OPENSQUILLA_LIVE_SEARCH") != "1":
        pytest.skip("set OPENSQUILLA_LIVE_SEARCH=1 to run live search tests")


@pytest.mark.asyncio
async def test_tavily_canonical_web_search_live_smoke() -> None:
    _require_live_search()
    if not os.environ.get("TAVILY_API_KEY"):
        pytest.skip("TAVILY_API_KEY not set")

    payload = await run_canonical_web_search(
        SearchOptions(
            query="Python latest release notes",
            mode="news",
            max_results=5,
            fetch_top_k=1,
            max_chars_per_source=1200,
            provider="tavily",
        )
    )

    assert payload["ok"] is True
    results = cast(list[dict[str, Any]], payload["results"])
    assert results
    first = results[0]
    assert str(first["url"]).startswith("http")
    assert first["domain"]
    assert first.get("snippet") or first.get("excerpt")
    assert payload["provider_attempts"][0]["provider"] == "tavily"
