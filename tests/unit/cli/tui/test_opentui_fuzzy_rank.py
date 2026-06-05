from __future__ import annotations

from opensquilla.cli.tui.opentui.completion import fuzzy_filter, fuzzy_rank


def test_fuzzy_filter_empty_query_preserves_input_order() -> None:
    items = ["resume", "compact", "reset"]

    assert fuzzy_filter("", items) == items


def test_fuzzy_filter_is_case_insensitive() -> None:
    assert fuzzy_filter("CMp", ["Reset", "COMPACT", "models"]) == ["COMPACT"]


def test_fuzzy_filter_ranks_compact_before_other_cmp_matches() -> None:
    ranked = fuzzy_filter("cmp", ["compress", "compact", "compare", "model"])

    assert ranked[0] == "compact"
    assert "compact" in ranked
    assert "model" not in ranked


def test_fuzzy_filter_matches_reset_and_resume_for_re() -> None:
    ranked = fuzzy_filter("re", ["compact", "resume", "reset", "render"])

    assert ranked[:2] == ["reset", "resume"]
    assert "compact" not in ranked


def test_fuzzy_filter_prefers_segment_start_and_early_matches() -> None:
    ranked = fuzzy_filter(
        "ma",
        [
            "src/domain.py",
            "src/cli/main.py",
            "docs/manual.md",
            "src/tui/messages.py",
        ],
    )

    assert ranked[:2] == ["src/cli/main.py", "docs/manual.md"]


def test_fuzzy_rank_returns_candidate_indexes_and_scores() -> None:
    ranked = fuzzy_rank("re", ["compact", "reset", "resume"])

    assert [index for index, _score in ranked] == [1, 2]
    assert ranked[0][1] >= ranked[1][1]
