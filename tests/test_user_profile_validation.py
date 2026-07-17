"""``validate_user_profile``: what it rejects, and what it must not miss.

``profile.json`` is hand-editable and is the only configuration surface for
``deny_models``. The failure this validator closes is silent: a typo in
``cost_sensitivity`` routes exactly as if the edit had never been made, because
``_cost_latency_weights`` falls back to a default on an unknown value. Refusing
the file at least says so.

The coverage test is the load-bearing one. The seam overlays *any* key the mock
baseline defines, while the validator hand-enumerates what it checks — two lists
with nothing tying them together. This branch removed three keys from the mock
profile, so re-adding one is a live motion, and a re-added key would be
overlayable from the hand-edited file with zero validation while every
neighbouring key is checked.
"""

from __future__ import annotations

from typing import Any

import pytest

from opensquilla.provider.ranking_router import (
    mock_user_profile,
    validate_user_profile,
)

# One deliberately invalid value per overlayable key, and the fragment the
# validator must name when it sees it. Driving the validator rather than
# listing "keys it checks" is the point: a third hand-maintained list would
# drift from the other two exactly like they drift from each other.
_BAD_VALUES: dict[str, tuple[str, Any]] = {
    "permission.allow_models": ("permission.allow_models", 123),
    "permission.deny_models": ("permission.deny_models", 123),
    "permission.risk_allowlist": ("permission.risk_allowlist", ["not_a_risk_level"]),
    "preference.quality_latency_tradeoff": (
        "preference.quality_latency_tradeoff",
        "not_a_tradeoff",
    ),
    "preference.cost_sensitivity": ("preference.cost_sensitivity", "not_a_sensitivity"),
    "history.positive_model_ids": ("history.positive_model_ids", 123),
    "history.negative_model_ids": ("history.negative_model_ids", 123),
    "history.feedback_count": ("history.feedback_count", -1),
}

# Overlayable but deliberately unvalidated, with the reason. Not a loophole: a
# key lands here only by someone writing down why it needs no check.
_EXEMPT: dict[str, str] = {
    "history.last_updated_at": (
        "A derived display stamp. Nothing routes on it, and content_version "
        "excludes it so it cannot even change a decision's identity. A bad "
        "value is visible in the file rather than silently altering routing."
    ),
}

_OVERLAID_SECTIONS = ("permission", "preference", "history")


def _overlayable_keys() -> set[str]:
    """Every key the read seam will overlay from a hand-edited file.

    Read from the mock baseline because that is what the seam gates on: it
    overlays a key only when the baseline already defines it.
    """
    baseline = mock_user_profile()
    keys: set[str] = set()
    for section in _OVERLAID_SECTIONS:
        for key in baseline.get(section, {}):
            keys.add(f"{section}.{key}")
    return keys


def test_every_overlayable_key_is_validated_or_explicitly_exempt() -> None:
    """The coverage invariant: adding a key must force a decision.

    Without this, adding a key back to ``mock_user_profile`` silently widens
    what a hand-edited file can set with no validation — reintroducing the
    "typo does nothing, quietly" failure for that one key while its neighbours
    stay checked. Failing here is the prompt to either validate it or say why
    it needs no validation.
    """
    covered = set(_BAD_VALUES) | set(_EXEMPT)
    uncovered = _overlayable_keys() - covered

    assert uncovered == set(), (
        "these keys are overlayable from the hand-edited profile but neither "
        "validated nor exempted: "
        f"{sorted(uncovered)}. Add a case to _BAD_VALUES, or exempt it in "
        "_EXEMPT with the reason it needs no check."
    )


def test_the_exempt_list_cannot_quietly_outlive_the_keys_it_excuses() -> None:
    """An exemption for a key that no longer exists is stale prose."""
    stale = set(_EXEMPT) - _overlayable_keys()
    assert stale == set(), f"_EXEMPT excuses keys that no longer exist: {sorted(stale)}"


@pytest.mark.parametrize(("dotted", "case"), sorted(_BAD_VALUES.items()))
def test_an_invalid_value_is_named_rather_than_swallowed(
    dotted: str, case: tuple[str, Any]
) -> None:
    """Each checked key must actually reject, and say which key it was.

    An error that does not name the key leaves the operator to guess which of
    their edits was refused.
    """
    fragment, bad = case
    section, key = dotted.split(".")

    errors = validate_user_profile({section: {key: bad}})

    assert errors, f"{dotted}={bad!r} was accepted"
    assert any(fragment in e for e in errors), (
        f"{dotted} was rejected but no error named it: {errors}"
    )


def test_the_baseline_itself_validates() -> None:
    """The profile every fallback returns must not be one we would refuse.

    If this fails, a refused file degrades to a baseline that is itself
    invalid, and the whole degrade path is built on sand.
    """
    assert validate_user_profile(mock_user_profile()) == []


def test_a_partial_profile_is_normal_and_not_an_error() -> None:
    """The stored file carries history only; the seam fills the rest."""
    assert validate_user_profile({}) == []
    assert validate_user_profile({"history": {"feedback_count": 3}}) == []


def test_a_valid_deny_models_edit_passes() -> None:
    """The edit the file exists for must not be collateral damage."""
    assert validate_user_profile({"permission": {"deny_models": ["openai/gpt-5"]}}) == []


def test_every_reason_a_profile_is_refused_is_reported_not_just_the_first() -> None:
    """The operator should fix one file once, not play whack-a-mole."""
    errors = validate_user_profile(
        {
            "permission": {"risk_allowlist": ["not_a_risk_level"]},
            "preference": {"cost_sensitivity": "not_a_sensitivity"},
        }
    )
    assert len(errors) == 2, errors
