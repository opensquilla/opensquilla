"""Opt-in live API matrix for the web retrieval stack.

These tests hit real public providers and public web pages only. They are
disabled by default and require both OPENSQUILLA_LIVE_SEARCH=1 and
OPENSQUILLA_LIVE_SEARCH_MATRIX=1 so the default CI suite only collects/skips
them.
"""

from __future__ import annotations

import inspect
import json
import os
from typing import Any, cast

import pytest
from typer.testing import CliRunner

import opensquilla.tools.builtin.web as web_module
from opensquilla.cli.main import app
from opensquilla.search.canonical import run_canonical_web_search
from opensquilla.search.types import SearchOptions, SearchResult
from opensquilla.tools.builtin.web_fetch import run_web_fetch_payload

pytestmark = pytest.mark.live_search

_QUERY = "Python release notes"
_PYTHON_DOMAIN = "python.org"


def _require_live_matrix() -> None:
    if os.environ.get("OPENSQUILLA_LIVE_SEARCH") != "1":
        pytest.skip("set OPENSQUILLA_LIVE_SEARCH=1 to run live search tests")
    if os.environ.get("OPENSQUILLA_LIVE_SEARCH_MATRIX") != "1":
        pytest.skip("set OPENSQUILLA_LIVE_SEARCH_MATRIX=1 to run live search matrix")


def _require_env(name: str) -> None:
    if not os.environ.get(name):
        pytest.skip(f"{name} not set")


def _results(payload: dict[str, Any]) -> list[dict[str, Any]]:
    results = payload.get("results")
    assert isinstance(results, list)
    return cast(list[dict[str, Any]], results)


def _domain_matches(domain: object, expected: str) -> bool:
    if not isinstance(domain, str):
        return False
    normalized = domain.lower().strip(".")
    expected = expected.lower().strip(".")
    return normalized == expected or normalized.endswith(f".{expected}")


@pytest.mark.asyncio
async def test_live_tavily_canonical_web_search_enforces_domain_filter() -> None:
    _require_live_matrix()
    _require_env("TAVILY_API_KEY")

    payload = await run_canonical_web_search(
        SearchOptions(
            query=_QUERY,
            mode="technical",
            max_results=5,
            fetch_top_k=1,
            max_chars_per_source=1000,
            include_domains=(_PYTHON_DOMAIN,),
            provider="tavily",
        )
    )

    assert payload["ok"] is True
    results = _results(payload)
    assert results
    assert all(_domain_matches(result.get("domain"), _PYTHON_DOMAIN) for result in results)
    assert payload["provider_attempts"][0] == {"provider": "tavily", "status": "success"}
    assert payload["diagnostics"]["fetched_count"] <= 1


@pytest.mark.asyncio
async def test_live_web_search_tool_returns_bounded_json() -> None:
    _require_live_matrix()
    _require_env("TAVILY_API_KEY")

    bare_web_search = inspect.unwrap(web_module.web_search)
    raw = await bare_web_search(
        _QUERY,
        mode="technical",
        max_results=3,
        fetch_top_k=1,
        max_chars_per_source=800,
        include_domains=[_PYTHON_DOMAIN],
    )
    payload = json.loads(raw)

    assert payload["ok"] is True
    results = _results(payload)
    assert results
    assert all(_domain_matches(result.get("domain"), _PYTHON_DOMAIN) for result in results)
    assert all(len(str(result.get("excerpt") or "")) <= 800 for result in results)


@pytest.mark.asyncio
async def test_live_brave_provider_accepts_recency_filter() -> None:
    _require_live_matrix()
    _require_env("BRAVE_SEARCH_API_KEY")

    from opensquilla.search.providers.brave import BraveSearchProvider

    results = await BraveSearchProvider().search(_QUERY, max_results=3, recency="year")

    assert results
    assert all(isinstance(result, SearchResult) for result in results)
    assert results[0].provider == "brave"
    assert results[0].url.startswith("http")


@pytest.mark.asyncio
async def test_live_exa_canonical_web_search_returns_content_metadata() -> None:
    _require_live_matrix()
    _require_env("EXA_API_KEY")

    payload = await run_canonical_web_search(
        SearchOptions(
            query=_QUERY,
            mode="technical",
            max_results=3,
            fetch_top_k=0,
            max_chars_per_source=1000,
            include_domains=(_PYTHON_DOMAIN,),
            provider="exa",
        )
    )

    assert payload["ok"] is True
    assert payload["provider_attempts"][0] == {"provider": "exa", "status": "success"}
    results = _results(payload)
    assert results
    assert all(row.get("provider") == "exa" for row in results)
    assert all(_domain_matches(row.get("domain"), _PYTHON_DOMAIN) for row in results)
    assert any(str(row.get("excerpt") or "").strip() for row in results)


@pytest.mark.asyncio
async def test_live_web_fetch_extracts_public_python_homepage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _require_live_matrix()
    monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)

    payload = await run_web_fetch_payload(
        "https://www.python.org/",
        extract_mode="markdown",
        max_chars=1200,
    )

    assert 200 <= int(payload["status"]) < 400
    assert payload["extractor"] in {"readability", "html2text", "raw"}
    text = str(payload["text"])
    assert text.startswith('<external-content source="')
    assert "Python" in text
    assert len(text) <= 1200


@pytest.mark.asyncio
async def test_live_web_fetch_can_explicitly_use_firecrawl() -> None:
    _require_live_matrix()
    _require_env("FIRECRAWL_API_KEY")

    payload = await run_web_fetch_payload(
        "https://www.python.org/",
        extract_mode="markdown",
        max_chars=1200,
        extractor="firecrawl",
    )

    assert 200 <= int(payload["status"]) < 400
    assert payload["extractor"] == "firecrawl"
    text = str(payload["text"])
    assert text.startswith('<external-content source="')
    assert "Python" in text


def test_live_cli_canonical_web_search_query_returns_json() -> None:
    _require_live_matrix()
    _require_env("TAVILY_API_KEY")

    result = CliRunner().invoke(
        app,
        [
            "search",
            "query",
            _QUERY,
            "--provider",
            "tavily",
            "--mode",
            "technical",
            "--max-results",
            "3",
            "--fetch-top-k",
            "1",
            "--max-chars-per-source",
            "800",
            "--include-domain",
            _PYTHON_DOMAIN,
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    results = _results(payload)
    assert results
    assert all(_domain_matches(row.get("domain"), _PYTHON_DOMAIN) for row in results)
