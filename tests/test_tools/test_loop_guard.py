from __future__ import annotations

import pytest

from opensquilla.result_budget import (
    ToolRunBudgetExceededError,
    ToolRunBudgetPolicy,
    ToolRunBudgetTracker,
    clamp_tool_arguments,
)


@pytest.mark.asyncio
async def test_research_search_counts_as_external_search() -> None:
    tracker = ToolRunBudgetTracker()

    reservation = await tracker.reserve_tool_call(
        tool_name="research_search",
        arguments={"query": "python release", "max_results": 10, "fetch_top_k": 3},
    )
    await tracker.commit_tool_result(reservation, "x" * 100)
    snapshot = await tracker.snapshot()

    assert reservation.counted_as_search is True
    assert reservation.counted_as_fetch is False
    assert reservation.counted_as_external_text is True
    assert snapshot["research_search_calls_used"] == 1
    assert snapshot["web_fetch_calls_used"] == 0
    assert snapshot["external_text_chars_used"] == 100


def test_research_search_clamp_leaves_bool_arguments_for_validation() -> None:
    arguments = {
        "query": "q",
        "max_results": True,
        "fetch_top_k": True,
        "max_chars_per_source": False,
    }

    clamped = clamp_tool_arguments(
        "research_search",
        arguments,
        ToolRunBudgetPolicy(
            max_research_search_results=8,
            max_research_fetch_top_k=2,
            max_research_chars_per_source=900,
        ),
    )

    assert clamped == arguments


def test_web_clamps_leave_bool_arguments_for_validation() -> None:
    search_args = {"query": "q", "max_results": True}
    fetch_args = {"url": "https://example.com", "max_chars": False}

    assert (
        clamp_tool_arguments(
            "web_search",
            search_args,
            ToolRunBudgetPolicy(max_web_search_results=8),
        )
        == search_args
    )
    assert (
        clamp_tool_arguments(
            "web_fetch",
            fetch_args,
            ToolRunBudgetPolicy(max_single_fetch_chars=900),
        )
        == fetch_args
    )


@pytest.mark.asyncio
async def test_loop_guard_blocks_repeated_identical_research_search() -> None:
    tracker = ToolRunBudgetTracker(
        ToolRunBudgetPolicy(max_repeated_retrievals_per_turn=2)
    )

    await tracker.reserve_tool_call(
        tool_name="research_search",
        arguments={
            "query": "  Python   Release  ",
            "provider": "tavily",
            "mode": "auto",
        },
    )
    await tracker.reserve_tool_call(
        tool_name="research_search",
        arguments={"query": "python release", "provider": "tavily", "mode": "auto"},
    )

    with pytest.raises(ToolRunBudgetExceededError) as exc_info:
        await tracker.reserve_tool_call(
            tool_name="research_search",
            arguments={
                "query": "PYTHON RELEASE",
                "provider": "tavily",
                "mode": "auto",
            },
        )

    assert exc_info.value.tool_name == "research_search"
    assert "repeated retrieval" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_loop_guard_counts_web_search_repeated_queries_too() -> None:
    tracker = ToolRunBudgetTracker(
        ToolRunBudgetPolicy(max_repeated_retrievals_per_turn=1)
    )

    await tracker.reserve_tool_call(
        tool_name="web_search",
        arguments={"query": "OpenSquilla"},
    )

    with pytest.raises(ToolRunBudgetExceededError):
        await tracker.reserve_tool_call(
            tool_name="web_search",
            arguments={"query": " opensquilla "},
        )


@pytest.mark.asyncio
async def test_loop_guard_snapshot_exposes_counts() -> None:
    tracker = ToolRunBudgetTracker()

    await tracker.reserve_tool_call(
        tool_name="research_search",
        arguments={
            "query": "Python Release",
            "provider": "tavily",
            "mode": "news",
        },
    )
    snapshot = await tracker.snapshot()

    assert snapshot["retrieval_loop_guard"] == [
        {
            "tool_name": "research_search",
            "query": "python release",
            "provider": "tavily",
            "mode": "news",
            "count": 1,
        }
    ]
