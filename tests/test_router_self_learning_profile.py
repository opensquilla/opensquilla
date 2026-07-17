"""The learned user profile: delta folding, revocation, and fail-closed writes.

The profile is the only thing that makes ``S_user`` do anything. With an empty
history every model scores the same neutral constant, so the term is a uniform
offset that cannot reorder candidates — inert, not merely approximate. These
lock the behaviour that makes it non-inert, and the privacy bar that keeps it
storable: identity tokens, enum tokens, and integers only.
"""

from __future__ import annotations

import json
from pathlib import Path

from opensquilla.squilla_router.self_learning.profile import (
    content_version,
    load_profile,
    profile_path,
    update_profile_for_rating,
)

_MODEL = "anthropic/claude-sonnet-4-5"
_OTHER = "openai/gpt-5"


def _history(home: Path) -> dict:
    profile = load_profile(home)
    assert profile is not None
    return profile["history"]


def test_absent_profile_loads_as_none(tmp_path: Path) -> None:
    assert load_profile(tmp_path) is None


def test_up_vote_puts_model_in_positive_list(tmp_path: Path) -> None:
    update_profile_for_rating(model=_MODEL, new_rating="up", home=tmp_path)
    history = _history(tmp_path)
    assert history["positive_model_ids"] == [_MODEL]
    assert history["negative_model_ids"] == []
    assert history["feedback_count"] == 1


def test_toggling_to_neutral_revokes_the_vote(tmp_path: Path) -> None:
    """The decrement is the whole point: without it a thumb is unrevokable."""
    update_profile_for_rating(model=_MODEL, new_rating="up", home=tmp_path)
    update_profile_for_rating(
        model=_MODEL,
        new_rating="neutral",
        previous_rating="up",
        previous_model=_MODEL,
        home=tmp_path,
    )
    history = _history(tmp_path)
    assert history["positive_model_ids"] == []
    assert history["feedback_count"] == 0


def test_flipping_up_to_down_counts_once_not_twice(tmp_path: Path) -> None:
    update_profile_for_rating(model=_MODEL, new_rating="up", home=tmp_path)
    update_profile_for_rating(
        model=_MODEL,
        new_rating="down",
        previous_rating="up",
        previous_model=_MODEL,
        home=tmp_path,
    )
    history = _history(tmp_path)
    assert history["positive_model_ids"] == []
    assert history["negative_model_ids"] == [_MODEL]
    assert history["feedback_count"] == 1


def test_equal_up_and_down_lands_in_neither_list(tmp_path: Path) -> None:
    """_user_score computes int(in_positive) - int(in_negative).

    Membership in both would cancel to zero anyway; excluding the model says
    the same thing without pretending to an opinion.
    """
    update_profile_for_rating(model=_MODEL, new_rating="up", home=tmp_path)
    update_profile_for_rating(model=_MODEL, new_rating="down", home=tmp_path)
    history = _history(tmp_path)
    assert history["positive_model_ids"] == []
    assert history["negative_model_ids"] == []
    assert history["feedback_count"] == 2


def test_revocation_decrements_the_model_it_was_credited_to(tmp_path: Path) -> None:
    """A revision must not move a count between models."""
    update_profile_for_rating(model=_OTHER, new_rating="up", home=tmp_path)
    update_profile_for_rating(
        model=_MODEL,
        new_rating="up",
        previous_rating="up",
        previous_model=_OTHER,
        home=tmp_path,
    )
    history = _history(tmp_path)
    assert history["positive_model_ids"] == [_MODEL]
    assert history["feedback_count"] == 1


def test_revising_a_row_that_was_never_credited_takes_nothing_away(
    tmp_path: Path,
) -> None:
    """A rating with no attribution was never folded in — so it cannot be undone.

    ``previous_model`` reads back as ``None`` for a row written at v1, before
    the profile existed. Treating that as "the same model" decrements a count
    the row never contributed: here the up belongs to a *different* decision,
    and guessing flips a liked model into a disliked one. ``max(0, ...)`` in
    ``_apply`` would hide the underflow, so only the sign is visible.
    """
    update_profile_for_rating(model=_MODEL, new_rating="up", home=tmp_path)

    update_profile_for_rating(
        model=_MODEL,
        new_rating="down",
        previous_rating="up",
        previous_model=None,
        home=tmp_path,
    )

    history = _history(tmp_path)
    assert history["negative_model_ids"] == []
    assert load_profile(tmp_path)["model_counts"] == {_MODEL: {"up": 1, "down": 1}}


def test_a_previous_model_too_malformed_to_credit_is_not_guessed(
    tmp_path: Path,
) -> None:
    """The other shape: stored on the row, but never credited to the profile.

    ``update_profile_for_rating`` fails closed on an unsafe model, while the
    feedback row keeps the raw string. Reading it back must reach the same
    verdict the write did — uncreditable — rather than fall back to ``model``.
    """
    update_profile_for_rating(model=_MODEL, new_rating="up", home=tmp_path)

    update_profile_for_rating(
        model=_MODEL,
        new_rating="down",
        previous_rating="up",
        previous_model="a model with spaces",
        home=tmp_path,
    )

    assert load_profile(tmp_path)["model_counts"] == {_MODEL: {"up": 1, "down": 1}}


def test_unresolvable_model_writes_nothing(tmp_path: Path) -> None:
    """Fail closed: crediting a guess is worse than learning nothing."""
    assert update_profile_for_rating(model=None, new_rating="up", home=tmp_path) is None
    assert update_profile_for_rating(model="  ", new_rating="up", home=tmp_path) is None
    assert not profile_path(tmp_path).exists()


def test_model_id_alphabet_is_enforced(tmp_path: Path) -> None:
    """Only identity tokens reach the file — never free text."""
    assert (
        update_profile_for_rating(
            model="a model with spaces and a sentence",
            new_rating="up",
            home=tmp_path,
        )
        is None
    )
    assert not profile_path(tmp_path).exists()


def test_version_changes_exactly_when_the_profile_changes(tmp_path: Path) -> None:
    """A constant version cannot explain a decision after the fact.

    ``last_updated_at`` is excluded so re-rating back to a previous state is
    recognisably the same profile, rather than a new one that happens to route
    identically.
    """
    first = update_profile_for_rating(model=_MODEL, new_rating="up", home=tmp_path)
    second = update_profile_for_rating(model=_OTHER, new_rating="up", home=tmp_path)
    assert first is not None and second is not None
    assert content_version(first) != content_version(second)

    # Same content, later day: same profile, so the same version.
    reverted = update_profile_for_rating(
        model=_OTHER,
        new_rating="neutral",
        previous_rating="up",
        previous_model=_OTHER,
        home=tmp_path,
    )
    assert reverted is not None
    assert content_version(reverted) == content_version(first)


def test_profile_holds_only_tokens_counts_and_enums(tmp_path: Path) -> None:
    """Privacy bar: same as feedback.jsonl. No prompt or response text."""
    update_profile_for_rating(model=_MODEL, new_rating="up", home=tmp_path)
    raw = json.loads(profile_path(tmp_path).read_text(encoding="utf-8"))
    assert set(raw["model_counts"]) == {_MODEL}
    assert raw["model_counts"][_MODEL] == {"up": 1, "down": 0}
    assert set(raw) == {
        "schema_version",
        "history",
        "model_counts",
    }


def test_the_file_does_not_carry_its_own_provenance(tmp_path: Path) -> None:
    """Provenance describes a read, so the writer stores none of it.

    A version stored here would be a hash of *this* body, while the one ranking
    reports hashes the resolved overlay — two different values under one name,
    so an operator matching a decision against the file finds a mismatch for an
    unchanged profile. A hand-edit that puts them back is dropped on the next
    thumb rather than left to keep asserting itself.
    """
    update_profile_for_rating(model=_MODEL, new_rating="up", home=tmp_path)
    path = profile_path(tmp_path)
    stored = json.loads(path.read_text(encoding="utf-8"))
    stored["profile_source"] = "fallback_mock"
    stored["profile_version"] = "sha256:deadbeefdeadbeef"
    path.write_text(json.dumps(stored), encoding="utf-8")

    update_profile_for_rating(model=_OTHER, new_rating="up", home=tmp_path)

    reread = json.loads(path.read_text(encoding="utf-8"))
    assert "profile_source" not in reread
    assert "profile_version" not in reread


def test_malformed_profile_degrades_to_none(tmp_path: Path) -> None:
    path = profile_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    assert load_profile(tmp_path) is None


def test_hand_edit_is_picked_up_without_a_restart(tmp_path: Path) -> None:
    """The cache keys on mtime, not on write.

    The file rewrites itself on every thumb, so an invalidation path has to
    exist regardless; keying it on write alone would update on a click but
    ignore a hand-edited deny_models, which is the file's whole point.
    """
    update_profile_for_rating(model=_MODEL, new_rating="up", home=tmp_path)
    assert load_profile(tmp_path) is not None

    path = profile_path(tmp_path)
    edited = json.loads(path.read_text(encoding="utf-8"))
    edited["permission"] = {"deny_models": [_OTHER]}
    path.write_text(json.dumps(edited), encoding="utf-8")

    reloaded = load_profile(tmp_path)
    assert reloaded is not None
    assert reloaded["permission"]["deny_models"] == [_OTHER]


def test_load_returns_a_copy_callers_cannot_corrupt_the_cache(tmp_path: Path) -> None:
    update_profile_for_rating(model=_MODEL, new_rating="up", home=tmp_path)
    first = load_profile(tmp_path)
    assert first is not None
    first["history"]["positive_model_ids"].append("injected")
    second = load_profile(tmp_path)
    assert second is not None
    assert second["history"]["positive_model_ids"] == [_MODEL]
