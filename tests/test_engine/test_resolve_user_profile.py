"""The read seam: how a stored profile reaches ranking.

``update_profile_for_rating`` writing a file and ranking reading one are only
useful if they meet. The unit tests on either side both pass while the seam is
disconnected, so these cover the join itself: a thumb goes in through the
learning surface and comes back out of ``_resolve_user_profile`` as history
that ``S_user`` can actually act on.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from opensquilla.engine.runtime import TurnRunner
from opensquilla.squilla_router.self_learning.profile import (
    profile_path,
    update_profile_for_rating,
)

_MODEL = "anthropic/claude-sonnet-4-5"


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the profile's default home at a tmp dir.

    The seam calls ``load_profile()`` with no argument on purpose — it reads
    the operator's real profile — so redirecting the env is the only honest
    way to exercise the path the runtime actually takes.
    """
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(tmp_path))
    return tmp_path


def test_absent_profile_resolves_to_the_mock_baseline(home: Path) -> None:
    profile = TurnRunner._resolve_user_profile(None)
    assert profile["history"]["positive_model_ids"] == []
    assert profile["profile_source"] == "fallback_mock"


def test_a_thumb_up_reaches_ranking_as_history(home: Path) -> None:
    """The end-to-end claim: rating the model changes what ranking reads."""
    update_profile_for_rating(model=_MODEL, new_rating="up")

    profile = TurnRunner._resolve_user_profile(None)
    assert profile["history"]["positive_model_ids"] == [_MODEL]
    assert profile["history"]["feedback_count"] == 1
    assert profile["profile_source"] == "global_json"
    assert profile["profile_version"].startswith("sha256:")


def test_revoking_the_thumb_reaches_ranking_too(home: Path) -> None:
    update_profile_for_rating(model=_MODEL, new_rating="up")
    update_profile_for_rating(
        model=_MODEL,
        new_rating="neutral",
        previous_rating="up",
        previous_model=_MODEL,
    )

    profile = TurnRunner._resolve_user_profile(None)
    assert profile["history"]["positive_model_ids"] == []


def test_baseline_defaults_survive_the_overlay(home: Path) -> None:
    """The stored file carries history only; the mock supplies the rest."""
    baseline = TurnRunner._resolve_user_profile(None)
    update_profile_for_rating(model=_MODEL, new_rating="up")

    merged = TurnRunner._resolve_user_profile(None)
    for section in ("permission", "preference"):
        assert merged[section] == baseline[section], section


def test_a_hand_edited_key_ranking_never_validated_is_not_overlaid(home: Path) -> None:
    """Only keys the baseline already defines are allowed through."""
    import json

    update_profile_for_rating(model=_MODEL, new_rating="up")
    path = profile_path(home)
    stored = json.loads(path.read_text(encoding="utf-8"))
    stored["history"]["invented_key"] = "should not survive"
    path.write_text(json.dumps(stored), encoding="utf-8")

    profile = TurnRunner._resolve_user_profile(None)
    assert "invented_key" not in profile["history"]
    assert profile["history"]["positive_model_ids"] == [_MODEL]


def _edit_stored(home: Path, mutate) -> None:
    import json

    path = profile_path(home)
    stored = json.loads(path.read_text(encoding="utf-8"))
    mutate(stored)
    path.write_text(json.dumps(stored), encoding="utf-8")


def test_a_valid_hand_edit_is_honored(home: Path) -> None:
    """deny_models has no TOML key — this file is the whole surface for it."""
    update_profile_for_rating(model=_MODEL, new_rating="up")
    _edit_stored(home, lambda s: s.setdefault("permission", {}).update(
        {"deny_models": ["openai/gpt-5"]}
    ))

    profile = TurnRunner._resolve_user_profile(None)
    assert profile["permission"]["deny_models"] == ["openai/gpt-5"]
    assert profile["profile_source"] == "global_json"


def test_a_hand_edit_changes_the_version_ranking_reports(home: Path) -> None:
    """The version has to cover the edit the file exists to make.

    ``deny_models`` is hard filtering and has no TOML key, so hand-editing it is
    this file's primary purpose — and it is the one change that never runs the
    write path. A version stamped only on a thumb would call two profiles with
    different filtering the same profile, which is the failure a constant
    version has, narrowed to the case that matters most.
    """
    update_profile_for_rating(model=_MODEL, new_rating="up")
    before = TurnRunner._resolve_user_profile(None)["profile_version"]

    _edit_stored(home, lambda s: s.setdefault("permission", {}).update(
        {"deny_models": ["openai/gpt-5"]}
    ))
    after = TurnRunner._resolve_user_profile(None)["profile_version"]

    assert before != after
    assert after.startswith("sha256:")


def test_the_file_cannot_pin_the_provenance_of_a_decision(home: Path) -> None:
    """Provenance describes the read, so the file does not get a vote.

    A stored ``profile_source``/``profile_version`` is the file describing
    itself. Trusting it lets a hand-edited file claim ``fallback_mock`` while
    ranking uses it, and stamp a version for content it does not have — the
    forensic record saying the opposite of what happened.
    """
    update_profile_for_rating(model=_MODEL, new_rating="up")

    def _lie(stored: dict) -> None:
        stored["profile_source"] = "fallback_mock"
        stored["profile_version"] = "sha256:deadbeefdeadbeef"

    _edit_stored(home, _lie)

    profile = TurnRunner._resolve_user_profile(None)
    # The file was used, so it must say so.
    assert profile["history"]["positive_model_ids"] == [_MODEL]
    assert profile["profile_source"] == "global_json"
    assert profile["profile_version"] != "sha256:deadbeefdeadbeef"


def test_an_invalid_enum_is_rejected_rather_than_silently_ignored(home: Path) -> None:
    """The failure this closes: ranking swallows a bad enum via its default.

    ``_cost_latency_weights`` falls back on an unknown ``cost_sensitivity``,
    so before validation a typo routed exactly as if the edit had never been
    made — and said nothing. Refusing the file at least tells the truth.
    """
    update_profile_for_rating(model=_MODEL, new_rating="up")
    _edit_stored(home, lambda s: s.setdefault("preference", {}).update(
        {"cost_sensitivity": "very_high"}
    ))

    profile = TurnRunner._resolve_user_profile(None)
    assert profile["profile_source"] == "fallback_mock"
    # Refused whole: the history that parsed does not sneak through either.
    assert profile["history"]["positive_model_ids"] == []


def test_an_invalid_risk_allowlist_is_rejected(home: Path) -> None:
    update_profile_for_rating(model=_MODEL, new_rating="up")
    _edit_stored(home, lambda s: s.setdefault("permission", {}).update(
        {"risk_allowlist": ["not_a_risk_level"]}
    ))

    assert TurnRunner._resolve_user_profile(None)["profile_source"] == "fallback_mock"


def test_a_raise_mid_overlay_reports_fallback_and_not_a_half_merge(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The third degrade path, and the one the other two tests miss.

    The overlay mutates ``base`` in place, so a raise partway through leaves it
    half-merged. Ranking must hear ``fallback_mock`` here for the same reason it
    does for a missing file — the spec's "any failure" — or a crashed load and
    an absent one report differently for the same "not using your profile".
    """
    update_profile_for_rating(model=_MODEL, new_rating="up")

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("validator exploded")

    monkeypatch.setattr(
        "opensquilla.provider.ranking_router.validate_user_profile", _boom
    )

    profile = TurnRunner._resolve_user_profile(None)
    assert profile["profile_source"] == "fallback_mock"
    assert profile["history"]["positive_model_ids"] == []


def test_unusable_profile_is_reported_not_passed_off_as_the_users_own(
    home: Path,
) -> None:
    path = profile_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")

    profile = TurnRunner._resolve_user_profile(None)
    assert profile["profile_source"] == "fallback_mock"
    assert profile["history"]["positive_model_ids"] == []
