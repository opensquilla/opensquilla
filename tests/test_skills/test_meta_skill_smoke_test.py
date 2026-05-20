"""Tests for meta-skill-smoke-test (G3+G4) and simulate_meta_resolution tool."""

from __future__ import annotations

from opensquilla.skills.creator.proposer import simulate_meta_resolution

VALID_SKILL_MD = """---
name: smoke-test-fixture
description: "Smoke-test fixture: handle PDF batches and persist memory."
kind: meta
meta_priority: 50
triggers:
  - "smoke fixture pdf batch"
provenance:
  origin: opensquilla-user
composition:
  steps:
    - id: x
      skill: pdf-toolkit
      with:
        task: "{{ inputs.user_message | xml_escape | truncate(512) }}"
---
# Smoke fixture
"""


def test_simulate_meta_resolution_matches_positive() -> None:
    matched = simulate_meta_resolution(
        skill_md=VALID_SKILL_MD,
        prompt="please run the smoke fixture pdf batch on these files",
        classifier_model="stub",
    )
    assert matched is True


def test_simulate_meta_resolution_rejects_negative() -> None:
    matched = simulate_meta_resolution(
        skill_md=VALID_SKILL_MD,
        prompt="check the weather in Tokyo",
        classifier_model="stub",
    )
    assert matched is False


def test_smoke_run_g3_g4_with_stub_fixture_gen(monkeypatch) -> None:
    from opensquilla.skills.creator.proposer import run_smoke_gates

    fixtures = {
        "positive": "please run the smoke fixture pdf batch on these files",
        "negative": "check the weather in Tokyo",
    }

    def fake_fixture_gen(_skill_md, kind, **_kwargs):
        return fixtures[kind]

    result = run_smoke_gates(
        skill_md=VALID_SKILL_MD,
        fixture_gen_fn=fake_fixture_gen,
        classifier_model="stub",
    )
    assert result["G3"]["passed"] is True
    assert result["G3"]["positive_fixture"] == fixtures["positive"]
    assert result["G4"]["passed"] is True
    assert result["G4"]["negative_fixture"] == fixtures["negative"]


def test_deterministic_fixture_positive_extracts_trigger() -> None:
    from opensquilla.skills.creator.proposer import _deterministic_fixture
    pos = _deterministic_fixture(VALID_SKILL_MD, "positive")
    assert "smoke fixture pdf batch" in pos


def test_deterministic_fixture_negative_is_unrelated() -> None:
    from opensquilla.skills.creator.proposer import _deterministic_fixture
    neg = _deterministic_fixture(VALID_SKILL_MD, "negative")
    assert "weather" in neg.lower()
