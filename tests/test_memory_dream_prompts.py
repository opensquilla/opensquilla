from __future__ import annotations

import pytest

from opensquilla.memory.dream.models import PromotionCandidate
from opensquilla.memory.dream.prompts import parse_promotion_patch


def _candidate(candidate_id: str = "cand-1") -> PromotionCandidate:
    return PromotionCandidate(
        candidate_id=candidate_id,
        source_path="memory/routing-preferences.md",
        snippet="- prefers routing to `model:x-ai/grok-4.5`",
        snippet_sha256="s",
        claim_sha256="c",
        score=0.9,
        reasons=["positive_or_manual_signal"],
        signal_counts={"positive": 1},
    )


_PATCH = (
    '{"operations":[{"op":"upsert","candidate_ids":["cand-1"],'
    '"section":"User Preferences","memory_id":"mem_grok",'
    '"text":"- prefers routing to `model:x-ai/grok-4.5`"}]}'
)


def _op_ids(text: str) -> list[list[str]]:
    patch = parse_promotion_patch(text, [_candidate()])
    return [op.candidate_ids for op in patch.operations]


def test_parses_clean_json() -> None:
    assert _op_ids(_PATCH) == [["cand-1"]]


def test_ignores_trailing_commentary_after_object() -> None:
    # The recurrent deepseek failure: a valid object followed by prose the greedy
    # regex used to swallow, yielding json.loads "Extra data".
    text = _PATCH + "\n\nI preserved the `model:` marker verbatim as instructed."
    assert _op_ids(text) == [["cand-1"]]


def test_ignores_trailing_second_object() -> None:
    text = _PATCH + '\n{"note":"done"}'
    assert _op_ids(text) == [["cand-1"]]


def test_skips_preamble_example_object() -> None:
    # A leading example object (no operations) must not shadow the real patch.
    text = 'Example: {"op":"skip"}\n\n' + _PATCH
    assert _op_ids(text) == [["cand-1"]]


def test_survives_markdown_fence() -> None:
    text = "```json\n" + _PATCH + "\n```"
    assert _op_ids(text) == [["cand-1"]]


def test_braces_inside_string_do_not_break_balance() -> None:
    text = (
        '{"operations":[{"op":"upsert","candidate_ids":["cand-1"],'
        '"section":"User Preferences","memory_id":"mem_grok",'
        '"text":"- prefers routing to `model:x-ai/grok-4.5` {not a brace}"}]}'
    )
    patch = parse_promotion_patch(text, [_candidate()])
    assert patch.operations[0].text.endswith("{not a brace}")


def test_no_json_raises() -> None:
    with pytest.raises(ValueError, match="did not contain JSON"):
        parse_promotion_patch("no json here at all", [_candidate()])


@pytest.mark.parametrize("op", ["upsert", "merge"])
def test_write_operation_without_text_is_rejected(op: str) -> None:
    text = (
        '{"operations":[{"op":"'
        + op
        + '","candidate_ids":["cand-1"],"text":"  "}]}'
    )
    with pytest.raises(ValueError, match="must contain non-empty text"):
        parse_promotion_patch(text, [_candidate()])


def test_candidate_cannot_be_assigned_to_multiple_operations() -> None:
    text = (
        '{"operations":['
        '{"op":"upsert","candidate_ids":["cand-1"],"text":"- first"},'
        '{"op":"merge","candidate_ids":["cand-1"],"text":"- second"}'
        "]}"
    )
    with pytest.raises(ValueError, match="assigned to multiple operations"):
        parse_promotion_patch(text, [_candidate()])
