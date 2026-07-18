"""Merge-then-filter in ``load_feedback_map``, and why the order is the point.

``_merged_by_decision`` collapses to the last row per ``decision_id`` *before*
``load_feedback_map`` drops non-votes. Both steps are obviously needed; only the
order makes revocation work, and nothing about reading either function in
isolation reveals that.

``load_feedback_map`` is the effective-rating source the offline trainer joins
on (``alignment``/``dataset``): each decision resolves to the one rating in
force. Reverse the order — filter to votes, then merge — and a revoking
``neutral`` row is skipped before it can supersede anything, so the stale ``up``
underneath is still returned as the effective rating. The trainer then joins a
retracted thumb to its sample as a live positive label, teaching toward a
decision the user took back.

The log cannot self-correct: it is pruned by ``retention_days``, so once the
neutral row ages out there is nothing left to reveal the ``up`` was revoked.
That is what makes an ordering nobody would think to test worth a test.
"""

from __future__ import annotations

from pathlib import Path

from opensquilla.squilla_router.self_learning.feedback import (
    load_feedback_map,
    write_feedback,
)

_AGENT = "agent-under-test"
_DECISION = "decision-1"
_MODEL = "anthropic/claude-sonnet-4-5"


def _submit(rating: str, home: Path, *, model: str | None = _MODEL) -> None:
    write_feedback(
        _AGENT,
        decision_id=_DECISION,
        session_key="session-1",
        turn_index=0,
        rating=rating,
        model=model,
        home=home,
    )


def test_a_revoking_neutral_supersedes_the_vote_it_revokes(tmp_path: Path) -> None:
    """The decision must be gone, not merely reported as neutral.

    ``load_feedback_map`` is the sole source of each decision's effective
    rating. If the revoked ``up`` survives here, the offline trainer joins a
    retracted thumb to its sample as a live positive label — against a log that,
    once pruned, can no longer reveal the retraction.
    """
    _submit("up", tmp_path)
    assert _DECISION in load_feedback_map(_AGENT, tmp_path)

    _submit("neutral", tmp_path)

    assert load_feedback_map(_AGENT, tmp_path) == {}


def test_the_last_row_wins_even_when_an_earlier_row_would_pass_the_filter(
    tmp_path: Path,
) -> None:
    """Merge order, isolated from revocation.

    Both rows are votes, so the rating filter cannot distinguish them: only
    file order decides. This fails the moment merging stops being last-wins.
    """
    _submit("up", tmp_path)
    _submit("down", tmp_path)

    entry = load_feedback_map(_AGENT, tmp_path)[_DECISION]
    assert entry.rating == "down"


def test_a_vote_reinstated_after_a_revocation_is_live_again(tmp_path: Path) -> None:
    """Revocation is not terminal — the merge has no memory of being emptied."""
    _submit("up", tmp_path)
    _submit("neutral", tmp_path)
    _submit("up", tmp_path)

    assert load_feedback_map(_AGENT, tmp_path)[_DECISION].rating == "up"


def test_revoking_one_decision_leaves_its_neighbours_alone(tmp_path: Path) -> None:
    """The merge keys on decision_id, so a revocation is scoped to one row."""
    _submit("up", tmp_path)
    write_feedback(
        _AGENT,
        decision_id="decision-2",
        session_key="session-1",
        turn_index=1,
        rating="up",
        model=_MODEL,
        home=tmp_path,
    )

    _submit("neutral", tmp_path)

    remaining = load_feedback_map(_AGENT, tmp_path)
    assert set(remaining) == {"decision-2"}
