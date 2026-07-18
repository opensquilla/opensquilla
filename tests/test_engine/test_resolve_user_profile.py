"""The read seam: how the derived profile reaches ranking.

``history`` is projected from Dream-consolidated global memory; ``permission``/
``preference`` come from the hand-edited file, the only surface for
``deny_models``. The projection and the ranking side each pass in isolation
while the seam is disconnected, so these cover the join: a preference written
into MEMORY.md the way Dream would consolidate it comes back out of
``_resolve_user_profile`` as history ``S_user`` can act on, and a hand-edited
``deny_models`` rides through beside it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from opensquilla.agents.scope import resolve_agent_workspace_dir
from opensquilla.engine.runtime import TurnRunner
from opensquilla.squilla_router.self_learning.profile import profile_path

_MODEL = "anthropic/claude-sonnet-4-5"
_OTHER = "openai/gpt-5"


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point both sources' default home at a tmp dir.

    The seam resolves the global workspace with ``config=None`` here, so it
    reads the same ``OPENSQUILLA_STATE_DIR`` the operator's real install would —
    the only honest way to exercise the path the runtime takes.
    """
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(tmp_path))
    return tmp_path


def _memory_md(home: Path) -> Path:
    return resolve_agent_workspace_dir("main", None) / "MEMORY.md"


def _write_memory(home: Path, text: str) -> None:
    path = _memory_md(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_profile(home: Path, payload: dict) -> None:
    path = profile_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _resolve() -> dict:
    return TurnRunner._resolve_user_profile(None, None)


def test_no_memory_no_file_is_the_mock_baseline(home: Path) -> None:
    profile = _resolve()
    assert profile["history"]["positive_model_ids"] == []
    assert profile["profile_source"] == "fallback_mock"


def test_present_but_empty_memory_is_a_derived_empty_profile(home: Path) -> None:
    """A memory that exists but says nothing is an empty *derived* profile.

    Distinct from "nothing read": ranking IS scoring against the operator's
    memory, it just carries no preference yet, so the source is honest about
    having read it.
    """
    _write_memory(home, "## Long-Term Memory\n- The user likes dark mode\n")
    profile = _resolve()
    assert profile["history"]["positive_model_ids"] == []
    assert profile["profile_source"] == "dream_memory"


def test_a_preference_memory_reaches_ranking_as_history(home: Path) -> None:
    """The end-to-end claim: a consolidated preference changes what ranking reads."""
    _write_memory(
        home,
        "## Routing preferences\n"
        f"- The operator prefers routing to `model:{_MODEL}` for coding\n",
    )
    profile = _resolve()
    assert profile["history"]["positive_model_ids"] == [_MODEL]
    assert profile["history"]["feedback_count"] == 1
    assert profile["profile_source"] == "dream_memory"
    assert profile["profile_version"].startswith("sha256:")


def test_an_avoid_memory_reaches_ranking_as_negative(home: Path) -> None:
    _write_memory(home, f"- we do not route to `model:{_OTHER}` anymore\n")
    profile = _resolve()
    assert profile["history"]["negative_model_ids"] == [_OTHER]
    assert profile["history"]["positive_model_ids"] == []


def test_baseline_defaults_survive_the_derivation(home: Path) -> None:
    """Memory carries history only; the mock supplies permission/preference."""
    baseline = _resolve()
    _write_memory(home, f"- prefers routing to `model:{_MODEL}`\n")
    merged = _resolve()
    for section in ("permission", "preference"):
        assert merged[section] == baseline[section], section


def test_a_valid_hand_edit_is_honored_beside_the_derived_history(home: Path) -> None:
    """deny_models has no TOML key — the file is the whole surface for it."""
    _write_memory(home, f"- prefers routing to `model:{_MODEL}`\n")
    _write_profile(home, {"permission": {"deny_models": [_OTHER]}})

    profile = _resolve()
    assert profile["permission"]["deny_models"] == [_OTHER]
    assert profile["history"]["positive_model_ids"] == [_MODEL]
    assert profile["profile_source"] == "dream_memory"


def test_a_hand_edit_changes_the_version_ranking_reports(home: Path) -> None:
    _write_memory(home, f"- prefers routing to `model:{_MODEL}`\n")
    before = _resolve()["profile_version"]

    _write_profile(home, {"permission": {"deny_models": [_OTHER]}})
    after = _resolve()["profile_version"]

    assert before != after
    assert after.startswith("sha256:")


def test_a_hand_edited_key_ranking_never_validated_is_not_overlaid(home: Path) -> None:
    """Only keys the baseline already defines are allowed through the file."""
    _write_profile(
        home, {"permission": {"deny_models": [_OTHER], "invented_key": "no"}}
    )
    profile = _resolve()
    assert "invented_key" not in profile["permission"]
    assert profile["permission"]["deny_models"] == [_OTHER]


def test_an_invalid_enum_refuses_the_file_and_drops_derived_history(home: Path) -> None:
    """A broken hand-edit means the operator's config is untrustworthy.

    ``_cost_latency_weights`` silently falls back on an unknown
    ``cost_sensitivity``, so a typo would route as if unmade. Refuse the whole
    profile — including the memory-derived history — rather than route on half
    of a config the operator got wrong.
    """
    _write_memory(home, f"- prefers routing to `model:{_MODEL}`\n")
    _write_profile(home, {"preference": {"cost_sensitivity": "very_high"}})

    profile = _resolve()
    assert profile["profile_source"] == "fallback_mock"
    assert profile["history"]["positive_model_ids"] == []


def test_an_invalid_risk_allowlist_refuses_the_file(home: Path) -> None:
    _write_profile(home, {"permission": {"risk_allowlist": ["not_a_risk_level"]}})
    assert _resolve()["profile_source"] == "fallback_mock"


def test_the_file_cannot_pin_the_provenance_of_a_decision(home: Path) -> None:
    """Provenance describes the read, so the file does not get a vote."""
    _write_memory(home, f"- prefers routing to `model:{_MODEL}`\n")
    _write_profile(
        home,
        {
            "permission": {"deny_models": [_OTHER]},
            "profile_source": "fallback_mock",
            "profile_version": "sha256:deadbeefdeadbeef",
        },
    )
    profile = _resolve()
    assert profile["history"]["positive_model_ids"] == [_MODEL]
    assert profile["profile_source"] == "dream_memory"
    assert profile["profile_version"] != "sha256:deadbeefdeadbeef"


def test_a_raise_mid_resolution_reports_fallback_not_a_half_merge(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Any failure degrades to the baseline, rebuilt clean, not half-merged."""
    _write_memory(home, f"- prefers routing to `model:{_MODEL}`\n")
    _write_profile(home, {"permission": {"deny_models": [_OTHER]}})

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("validator exploded")

    monkeypatch.setattr(
        "opensquilla.provider.ranking_router.validate_user_profile", _boom
    )
    profile = _resolve()
    assert profile["profile_source"] == "fallback_mock"
    assert profile["history"]["positive_model_ids"] == []


def test_a_malformed_profile_file_with_no_memory_reports_fallback(home: Path) -> None:
    path = profile_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")

    profile = _resolve()
    assert profile["profile_source"] == "fallback_mock"
    assert profile["history"]["positive_model_ids"] == []
