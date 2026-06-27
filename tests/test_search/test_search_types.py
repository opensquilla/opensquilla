from __future__ import annotations

from dataclasses import FrozenInstanceError, asdict

import pytest

from opensquilla.search.types import SearchDiagnostics, SearchHit, SearchOptions, SearchResult


def test_search_result_keeps_existing_constructor_shape() -> None:
    result = SearchResult("Title", "https://example.com", "Snippet")

    assert result.title == "Title"
    assert result.url == "https://example.com"
    assert result.snippet == "Snippet"
    assert result.source == ""
    assert result.published_at is None
    assert result.provider == ""
    assert result.score is None
    assert result.highlights == []
    assert result.content == ""
    assert result.raw_metadata == {}


def test_search_options_clamps_public_limits() -> None:
    options = SearchOptions(
        query="  OpenSquilla search  ",
        max_results=100,
        fetch_top_k=100,
        max_chars_per_source=100_000,
        include_domains=["Example.com"],  # type: ignore[arg-type]
        exclude_domains=["Spam.example"],  # type: ignore[arg-type]
    )

    assert options.query == "OpenSquilla search"
    assert options.max_results == 20
    assert options.fetch_top_k == 5
    assert options.max_chars_per_source == 5000
    assert options.include_domains == ("example.com",)
    assert options.exclude_domains == ("spam.example",)


def test_search_options_clamps_lower_bounds_and_is_frozen() -> None:
    options = SearchOptions(
        query="q",
        max_results=0,
        fetch_top_k=-1,
        max_chars_per_source=1,
    )

    assert options.max_results == 1
    assert options.fetch_top_k == 0
    assert options.max_chars_per_source == 200
    with pytest.raises(FrozenInstanceError):
        options.query = "changed"  # type: ignore[misc]


def test_search_options_treats_single_domain_strings_as_one_domain() -> None:
    options = SearchOptions(
        query="q",
        include_domains="example.com",  # type: ignore[arg-type]
        exclude_domains="docs.example.com",  # type: ignore[arg-type]
    )

    assert options.include_domains == ("example.com",)
    assert options.exclude_domains == ("docs.example.com",)


def test_search_hit_is_json_safe_with_defaults() -> None:
    hit = SearchHit(
        title="Title",
        url="https://example.com/a",
        canonical_url="https://example.com/a",
        domain="example.com",
        provider="tavily",
        snippet="Snippet",
    )

    data = asdict(hit)

    assert data["fetched"] is False
    assert data["fetch_status"] == "not_requested"
    assert data["excerpt"] == ""
    assert data["extractor"] == ""
    assert data["content_truncated"] is False
    assert data["raw_metadata"] == {}


def test_search_diagnostics_has_safe_defaults() -> None:
    diagnostics = SearchDiagnostics(query="q", mode="auto")

    assert diagnostics.provider_attempts == []
    assert diagnostics.fallback_from == ""
    assert diagnostics.fetched_count == 0
    assert diagnostics.fetch_failed_count == 0
    assert diagnostics.duplicate_count == 0
    assert diagnostics.returned_chars == 0
    assert diagnostics.budget_clamped is False
    assert diagnostics.loop_guard == {}
