from __future__ import annotations

import inspect
import json

import pytest

import opensquilla.tools.builtin.research_search as research_search_module
from opensquilla.search.types import SearchOptions


@pytest.mark.asyncio
async def test_research_search_tool_builds_options_and_returns_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen_options: list[SearchOptions] = []

    async def fake_run_research_search(options: SearchOptions) -> dict[str, object]:
        seen_options.append(options)
        return {
            "ok": True,
            "query": options.query,
            "mode": options.mode,
            "provider_attempts": [{"provider": "tavily", "status": "success"}],
            "diagnostics": {"budget_clamped": True},
            "results": [
                {
                    "title": "Python release",
                    "url": "https://www.python.org/downloads/",
                    "excerpt": "Python release notes",
                }
            ],
        }

    monkeypatch.setattr(
        research_search_module,
        "run_research_search",
        fake_run_research_search,
    )

    bare_research_search = inspect.unwrap(research_search_module.research_search)
    result = await bare_research_search(
        "python release",
        mode="auto",
        provider="exa",
        max_results=10,
        fetch_top_k=3,
        max_chars_per_source=1500,
        include_domains=["python.org"],
        exclude_domains=[],
        recency="month",
    )
    payload = json.loads(result)

    assert payload["query"] == "python release"
    assert payload["mode"] == "auto"
    assert payload["provider_attempts"] == [{"provider": "tavily", "status": "success"}]
    assert payload["diagnostics"] == {"budget_clamped": True}
    assert payload["results"][0]["excerpt"] == "Python release notes"
    assert "raw_metadata" not in payload["results"][0]

    assert seen_options == [
        SearchOptions(
            query="python release",
            mode="auto",
            max_results=10,
            fetch_top_k=3,
            max_chars_per_source=1500,
            include_domains=("python.org",),
            exclude_domains=(),
            recency="month",
            provider="exa",
        )
    ]
    assert seen_options[0].include_domains == ("python.org",)


@pytest.mark.asyncio
async def test_research_search_tool_maps_auto_provider_to_default_orchestrator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen_options: list[SearchOptions] = []

    async def fake_run_research_search(options: SearchOptions) -> dict[str, object]:
        seen_options.append(options)
        return {"ok": True, "query": options.query, "results": []}

    monkeypatch.setattr(
        research_search_module,
        "run_research_search",
        fake_run_research_search,
    )

    bare_research_search = inspect.unwrap(research_search_module.research_search)
    result = await bare_research_search("python release", provider="auto")
    payload = json.loads(result)

    assert payload["ok"] is True
    assert seen_options[0].provider is None


@pytest.mark.asyncio
async def test_research_search_tool_rejects_invalid_provider_without_calling_orchestrator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_run_research_search(options: SearchOptions) -> dict[str, object]:
        raise AssertionError("run_research_search should not be called")

    monkeypatch.setattr(
        research_search_module,
        "run_research_search",
        fake_run_research_search,
    )

    bare_research_search = inspect.unwrap(research_search_module.research_search)
    result = await bare_research_search("python release", provider="serpapi")
    payload = json.loads(result)

    assert payload == {
        "ok": False,
        "error_kind": "invalid_request",
        "error": "Invalid provider. Expected one of: auto, brave, duckduckgo, exa, tavily.",
    }


@pytest.mark.asyncio
async def test_research_search_tool_rejects_invalid_mode_without_calling_orchestrator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_run_research_search(options: SearchOptions) -> dict[str, object]:
        raise AssertionError("run_research_search should not be called")

    monkeypatch.setattr(
        research_search_module,
        "run_research_search",
        fake_run_research_search,
    )

    bare_research_search = inspect.unwrap(research_search_module.research_search)
    result = await bare_research_search("python release", mode="invalid")
    payload = json.loads(result)

    assert payload == {
        "ok": False,
        "error_kind": "invalid_request",
        "error": "Invalid mode. Expected one of: auto, broad, news, technical.",
    }


@pytest.mark.asyncio
async def test_research_search_tool_rejects_invalid_recency_without_calling_orchestrator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_run_research_search(options: SearchOptions) -> dict[str, object]:
        raise AssertionError("run_research_search should not be called")

    monkeypatch.setattr(
        research_search_module,
        "run_research_search",
        fake_run_research_search,
    )

    bare_research_search = inspect.unwrap(research_search_module.research_search)
    result = await bare_research_search("python release", recency="hour")
    payload = json.loads(result)

    assert payload == {
        "ok": False,
        "error_kind": "invalid_request",
        "error": "Invalid recency. Expected one of: day, month, week, year.",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"query": 123}, "query must be a non-empty string."),
        (
            {"query": "python release", "max_results": "bad"},
            "max_results must be an integer.",
        ),
        (
            {"query": "python release", "include_domains": "example.com"},
            "include_domains must be a list or tuple of strings.",
        ),
        (
            {"query": "python release", "include_domains": [123]},
            "include_domains must be a list or tuple of strings.",
        ),
        (
            {"query": "python release", "exclude_domains": [object()]},
            "exclude_domains must be a list or tuple of strings.",
        ),
    ],
)
async def test_research_search_tool_rejects_malformed_args_without_calling_orchestrator(
    monkeypatch: pytest.MonkeyPatch,
    kwargs: dict[str, object],
    message: str,
) -> None:
    async def fake_run_research_search(options: SearchOptions) -> dict[str, object]:
        raise AssertionError("run_research_search should not be called")

    monkeypatch.setattr(
        research_search_module,
        "run_research_search",
        fake_run_research_search,
    )

    bare_research_search = inspect.unwrap(research_search_module.research_search)
    result = await bare_research_search(**kwargs)  # type: ignore[arg-type]
    payload = json.loads(result)

    assert payload == {
        "ok": False,
        "error_kind": "invalid_request",
        "error": message,
    }
