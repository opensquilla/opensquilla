import json

from opensquilla.engine.runtime import _persisted_tool_result_segment
from opensquilla.engine.types import ToolResultEvent


def test_persisted_tool_result_keeps_oversized_json_parseable_with_provider() -> None:
    result = json.dumps(
        {
            "query": "ClickUp pricing plans 2025 2026 per seat",
            "provider": "brave",
            "results": [
                {
                    "title": f"Result {idx}",
                    "url": f"https://example.com/{idx}",
                    "snippet": "x" * 700,
                }
                for idx in range(5)
            ],
        },
        ensure_ascii=False,
        indent=2,
    )
    assert len(result) > 2000

    segment = _persisted_tool_result_segment(
        ToolResultEvent(
            tool_use_id="call_1",
            tool_name="web_search",
            result=result,
            is_error=False,
        )
    )

    assert segment["provider"] == "brave"
    assert segment["query"] == "ClickUp pricing plans 2025 2026 per seat"
    assert segment["result_truncated"] is True
    assert segment["result_original_chars"] == len(result)
    assert len(segment["result"]) <= 2000

    preview = json.loads(segment["result"])
    assert preview["provider"] == "brave"
    assert preview["query"] == "ClickUp pricing plans 2025 2026 per seat"
    assert preview["result_truncated"] is True
    assert preview["result_original_chars"] == len(result)


def test_persisted_web_search_result_promotes_nested_diagnostics() -> None:
    result = json.dumps(
        {
            "ok": True,
            "query": "OpenSquilla search architecture",
            "mode": "technical",
            "provider_attempts": [
                {"provider": "exa", "status": "error", "error_kind": "network"},
                {"provider": "brave", "status": "success"},
            ],
            "diagnostics": {
                "selected_provider": "brave",
                "fallback_from": "exa",
                "fetched_count": 2,
                "fetch_failed_count": 1,
                "returned_chars": 2800,
                "budget_clamped": True,
                "recency_supported": False,
                "recency_degraded": True,
                "provider_attempts": [
                    {"provider": "exa", "status": "error", "error_kind": "network"},
                    {"provider": "brave", "status": "success"},
                ],
            },
            "results": [
                {
                    "title": f"Result {idx}",
                    "url": f"https://example.com/{idx}",
                    "excerpt": "x" * 900,
                }
                for idx in range(5)
            ],
        },
        ensure_ascii=False,
        indent=2,
    )
    assert len(result) > 2000

    segment = _persisted_tool_result_segment(
        ToolResultEvent(
            tool_use_id="call_web_search_diagnostics",
            tool_name="web_search",
            result=result,
            is_error=False,
        )
    )

    assert segment["selected_provider"] == "brave"
    assert segment["fallback_from"] == "exa"
    assert segment["provider_attempt_count"] == 2
    assert segment["fetched_count"] == 2
    assert segment["fetch_failed_count"] == 1
    assert segment["returned_chars"] == 2800
    assert segment["budget_clamped"] is True
    assert segment["recency_supported"] is False
    assert segment["recency_degraded"] is True


def test_persisted_web_search_result_keeps_sources_with_complete_urls() -> None:
    long_excerpt = "Long fetched article body. " * 120
    result = json.dumps(
        {
            "ok": True,
            "query": "Lionel Messi retirement 2026",
            "mode": "auto",
            "sources": [
                {
                    "rank": 1,
                    "title": "Messi retirement dismissed with one condition clear",
                    "url": "https://thefootballfaithful.com/messi-retirement-dismissed-one-condition-clear/",
                    "canonical_url": "https://thefootballfaithful.com/messi-retirement-dismissed-one-condition-clear/",
                    "domain": "thefootballfaithful.com",
                    "provider": "duckduckgo",
                    "fetched": True,
                }
            ],
            "results": [
                {
                    "rank": 1,
                    "title": "Messi retirement dismissed with one condition clear",
                    "url": "https://thefootballfaithful.com/messi-retirement-dismissed-one-condition-clear/",
                    "excerpt": long_excerpt,
                    "provider": "duckduckgo",
                }
            ],
        },
        ensure_ascii=False,
        indent=2,
    )
    assert len(result) > 2000

    segment = _persisted_tool_result_segment(
        ToolResultEvent(
            tool_use_id="call_web_search_sources",
            tool_name="web_search",
            result=result,
            is_error=False,
        )
    )

    assert segment["result_truncated"] is True
    assert segment["sources"] == [
        {
            "rank": 1,
            "title": "Messi retirement dismissed with one condition clear",
            "url": "https://thefootballfaithful.com/messi-retirement-dismissed-one-condition-clear/",
            "canonical_url": "https://thefootballfaithful.com/messi-retirement-dismissed-one-condition-clear/",
            "domain": "thefootballfaithful.com",
            "provider": "duckduckgo",
            "fetched": True,
        }
    ]
    assert not segment["sources"][0]["url"].endswith("…")


def test_persisted_web_search_result_derives_sources_from_results_when_missing() -> None:
    result = json.dumps(
        {
            "ok": True,
            "query": "source fallback",
            "provider_attempts": [{"provider": "duckduckgo", "status": "success"}],
            "results": [
                {
                    "rank": 1,
                    "title": "Fallback source",
                    "url": "https://example.com/fallback-source?utm=tracking",
                    "canonical_url": "https://example.com/fallback-source",
                    "domain": "example.com",
                    "provider": "duckduckgo",
                    "fetched": False,
                    "excerpt": "x" * 3000,
                }
            ],
        },
        ensure_ascii=False,
        indent=2,
    )
    assert len(result) > 2000

    segment = _persisted_tool_result_segment(
        ToolResultEvent(
            tool_use_id="call_web_search_sources_fallback",
            tool_name="web_search",
            result=result,
            is_error=False,
        )
    )

    assert segment["sources"] == [
        {
            "rank": 1,
            "title": "Fallback source",
            "url": "https://example.com/fallback-source?utm=tracking",
            "canonical_url": "https://example.com/fallback-source",
            "domain": "example.com",
            "provider": "duckduckgo",
            "fetched": False,
        }
    ]


def test_persisted_tool_result_bounds_oversized_segment_metadata() -> None:
    result = json.dumps(
        {
            "provider": "brave",
            "query": "q" * 100_000,
            "error": "e" * 100_000,
            "results": [{"snippet": "x" * 700}],
        },
        ensure_ascii=False,
        indent=2,
    )

    segment = _persisted_tool_result_segment(
        ToolResultEvent(
            tool_use_id="call_oversized_metadata",
            tool_name="web_search",
            result=result,
            is_error=False,
        )
    )

    assert segment["provider"] == "brave"
    assert len(segment["query"]) == 256
    assert segment["query"].endswith("…")
    assert len(segment["error"]) == 256
    assert segment["error"].endswith("…")
    assert "fallback_from" not in segment
    assert len(segment["result"]) <= 2000
    assert len(json.dumps(segment, ensure_ascii=False)) < 3000


def test_persisted_tool_result_keeps_short_result_unchanged() -> None:
    result = '{"provider": "brave", "results": []}'

    segment = _persisted_tool_result_segment(
        ToolResultEvent(
            tool_use_id="call_2",
            tool_name="web_search",
            result=result,
            is_error=False,
        )
    )

    assert segment == {
        "type": "tool_result",
        "tool_use_id": "call_2",
        "name": "web_search",
        "result": result,
        "is_error": False,
    }


def test_persisted_tool_result_marks_oversized_non_json_prefix() -> None:
    result = "abc" * 1000

    segment = _persisted_tool_result_segment(
        ToolResultEvent(
            tool_use_id="call_3",
            tool_name="exec_command",
            result=result,
            is_error=False,
        )
    )

    assert segment["result"] == result[:2000]
    assert segment["result_truncated"] is True
    assert segment["result_original_chars"] == len(result)
