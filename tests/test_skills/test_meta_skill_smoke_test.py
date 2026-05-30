"""Tests for skill-creator-smoke-test (G3+G4) and simulate_meta_resolution tool."""

from __future__ import annotations

import json

import pytest

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


def test_smoke_emits_degraded_true_on_stub_classifier() -> None:
    """Stub classifier_model marks G3/G4 records as degraded."""
    from opensquilla.skills.creator.proposer import (
        _deterministic_fixture,
        run_smoke_gates,
    )
    result = run_smoke_gates(
        skill_md=VALID_SKILL_MD,
        fixture_gen_fn=_deterministic_fixture,
        classifier_model="stub",
    )
    assert result["degraded"] is True
    assert result["G3"]["degraded"] is True
    assert result["G4"]["degraded"] is True


def test_deterministic_fixture_decodes_unicode_escape() -> None:
    """The Jinja tojson filter escapes non-ASCII triggers as \\uXXXX. The
    deterministic fixture extractor must decode those back to real Unicode
    so the trigger matcher can find them in the generated fixture."""
    from opensquilla.skills.creator.proposer import _deterministic_fixture

    # Mimic a SKILL.md that creator's templates would actually produce
    # for a Chinese-named meta-skill (tojson emits \uXXXX form)
    skill_md_with_escaped_zh_trigger = '''---
name: "pdf-digest-zh"
description: "Test"
kind: meta
meta_priority: 50
triggers:
  - "pdf\\u6458\\u8981"
  - "\\u8bb0\\u5fc6pdf"
---
# zh trigger test
'''
    fixture = _deterministic_fixture(skill_md_with_escaped_zh_trigger, "positive")
    # The fixture should contain the ACTUAL Chinese chars, not the literal \u form
    assert "pdf摘要" in fixture, f"expected decoded Chinese in {fixture!r}"
    # And it should NOT contain literal backslash-u
    assert "\\u" not in fixture, f"unicode escape not decoded in {fixture!r}"


def test_meta_skill_smoke_run_marked_degraded() -> None:
    """N19 regression: meta_skill_smoke_run always uses deterministic
    fixtures (no real LLM), so result must indicate degraded=True.
    Lambda-wrapping _deterministic_fixture previously broke identity
    detection in run_smoke_gates, causing degraded=False."""
    import json as _json

    from opensquilla.skills.creator.proposer import meta_skill_smoke_run

    skill_md = """---
name: "smoke-degraded-test"
description: "Test smoke degraded flagging."
kind: meta
meta_priority: 50
triggers:
  - "smoke degraded test"
provenance:
  origin: opensquilla-user
composition:
  steps:
    - id: only
      skill: summarize
      with:
        task: "{{ inputs.user_message | xml_escape | truncate(512) }}"
---
"""
    raw = meta_skill_smoke_run(skill_md, "openai/gpt-4o-mini", "openrouter/auto")
    result = _json.loads(raw)
    # Top-level degraded flag must be True
    assert result.get("degraded") is True, (
        f"smoke result should be marked degraded at top level; got: {result}"
    )
    # Per-gate flags must also be True
    assert result.get("G3", {}).get("degraded") is True, (
        f"G3 should be marked degraded; got: {result.get('G3')}"
    )
    assert result.get("G4", {}).get("degraded") is True, (
        f"G4 should be marked degraded; got: {result.get('G4')}"
    )


@pytest.mark.asyncio
async def test_meta_skill_smoke_run_tool_uses_llm_fixture_context() -> None:
    from opensquilla.skills.creator.proposer import (
        meta_skill_smoke_run_tool,
        reset_smoke_fixture_context,
        set_smoke_fixture_context,
    )

    async def llm_chat(_system: str, user: str) -> str:
        if "positive" in user.lower():
            return "please run the smoke degraded test"
        return "help me compare phone plans"

    skill_md = """---
name: "smoke-degraded-test"
description: "Test smoke fixture context."
kind: meta
meta_priority: 50
triggers:
  - "smoke degraded test"
composition:
  steps:
    - id: only
      skill: summarize
      with:
        task: "{{ inputs.user_message | xml_escape | truncate(512) }}"
---
"""
    token = set_smoke_fixture_context({"llm_chat": llm_chat})
    try:
        result = json.loads(await meta_skill_smoke_run_tool(
            skill_md,
            "openai/gpt-4o-mini",
            "openrouter/auto",
        ))
    finally:
        reset_smoke_fixture_context(token)

    assert result["degraded"] is False
    assert result["G3"]["positive_fixture"] == "please run the smoke degraded test"
    assert result["G4"]["negative_fixture"] == "help me compare phone plans"


def test_smoke_g3_passes_with_chinese_triggers() -> None:
    """End-to-end: a Chinese-trigger SKILL.md should pass G3 when the
    fixture is generated by _deterministic_fixture and simulate_meta_resolution
    runs the trigger match. Previously G3 was always false for Chinese
    triggers because of unicode-escape mismatch."""
    from opensquilla.skills.creator.proposer import _deterministic_fixture, run_smoke_gates

    skill_md = '''---
name: "zh-trigger-skill"
description: "Sample skill with Chinese triggers for G3 smoke test."
kind: meta
meta_priority: 50
triggers:
  - "pdf\\u6458\\u8981"
  - "\\u8bb0\\u5fc6pdf"
provenance:
  origin: opensquilla-user
composition:
  steps:
    - id: only
      skill: summarize
      with:
        task: "{{ inputs.user_message | xml_escape | truncate(512) }}"
---
'''

    result = run_smoke_gates(
        skill_md=skill_md,
        fixture_gen_fn=_deterministic_fixture,
        classifier_model="stub",
    )
    assert result["G3"]["passed"] is True, (
        f"G3 should match decoded Chinese trigger; "
        f"fixture={result['G3'].get('positive_fixture')!r}"
    )
