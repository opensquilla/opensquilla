"""Offline router-accuracy harness for ``llm_classify`` meta-skills (Step D.1).

Two layers of assertions per parametrised fixture:

1. **Schema sync**: the fixture's ``expected_choice`` is one of the
   bundled meta-skill's actual ``output_choices``. Catches drift where
   the SKILL.md adds/removes a choice but the fixture file misses the
   update.

2. **Pipeline propagation**: when the (mocked) LLMChat returns the
   ``expected_choice`` verbatim, ``run_llm_classify_step`` produces
   that label. This verifies the prompt-build / coerce / output chain
   without depending on a real provider — it's the "if the LLM gives
   the right answer, the pipeline echoes it" sanity gate.

Live multi-model accuracy measurement (D.2) lives in a separate file
marked ``@pytest.mark.llm_router_acc`` and is maintainer-only.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from router_fixtures import ALL_CASES, RouterCase, migration_assistant

from opensquilla.engine.types import AgentEvent
from opensquilla.skills.loader import SkillLoader
from opensquilla.skills.meta.executors.llm_classify import run_llm_classify_step
from opensquilla.skills.meta.parser import parse_meta_plan
from opensquilla.skills.meta.types import MetaStep

_SKILLS_DIR = Path(__file__).resolve().parents[2] / "src" / "opensquilla" / "skills"
_BUNDLED_DIR = _SKILLS_DIR / "bundled"
_EXP_DIR = _SKILLS_DIR / "exp"


@pytest.fixture(scope="module")
def _loader(tmp_path_factory: pytest.TempPathFactory) -> SkillLoader:
    """Module-scoped loader against the real in-tree skill catalogs."""
    snapshot = tmp_path_factory.mktemp("router-acc") / "snapshot.json"
    loader = SkillLoader(
        bundled_dir=_BUNDLED_DIR,
        extra_dirs=[_EXP_DIR],
        snapshot_path=snapshot,
    )
    loader.invalidate_cache()
    loader.load_all()
    return loader


def _classify_step_of(loader: SkillLoader, skill_name: str) -> MetaStep:
    spec = loader.get_by_name(skill_name)
    assert spec is not None, f"skill {skill_name!r} not found"
    plan = parse_meta_plan(spec)
    assert plan is not None, f"plan for {skill_name!r} did not parse"
    classify = next((s for s in plan.steps if s.kind == "llm_classify"), None)
    assert classify is not None, (
        f"skill {skill_name!r} has no llm_classify step — "
        f"fixture file is for a non-router meta-skill"
    )
    return classify


def _fixture_outputs_for(skill_name: str) -> dict[str, str]:
    if skill_name == migration_assistant.SKILL_NAME:
        return {"migration_intake": "Synthetic migration intake."}
    return {}


@pytest.mark.parametrize(
    "skill_name, fixture_choices",
    [
        (migration_assistant.SKILL_NAME, migration_assistant.OUTPUT_CHOICES),
    ],
)
def test_fixture_output_choices_match_bundled_skill(
    _loader: SkillLoader,
    skill_name: str,
    fixture_choices: tuple[str, ...],
) -> None:
    """Each fixture module declares its OUTPUT_CHOICES locally — assert it
    matches the bundled SKILL.md so a choice added in one but not the
    other is caught immediately."""
    classify = _classify_step_of(_loader, skill_name)
    assert tuple(classify.output_choices) == fixture_choices, (
        f"{skill_name!r} fixture OUTPUT_CHOICES drifted from SKILL.md: "
        f"fixture={fixture_choices}, bundled={classify.output_choices}"
    )


@pytest.mark.parametrize("case", ALL_CASES, ids=lambda c: f"{c.skill}:{c.note}")
def test_fixture_expected_choice_is_valid(_loader: SkillLoader, case: RouterCase) -> None:
    """Every fixture's expected_choice must exist in the target router
    skill's actual output_choices (typo / drift prevention)."""
    classify = _classify_step_of(_loader, case.skill)
    assert case.expected_choice in classify.output_choices, (
        f"fixture {case.note!r}: expected_choice {case.expected_choice!r} "
        f"is not in {case.skill!r}'s output_choices {classify.output_choices}"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ALL_CASES, ids=lambda c: f"{c.skill}:{c.note}")
async def test_routing_pipeline_propagates_expected_label(
    _loader: SkillLoader,
    case: RouterCase,
) -> None:
    """When the mocked LLM returns the expected label verbatim, the
    pipeline must surface that label as the step output. This isolates
    pipeline correctness from LLM accuracy (live accuracy is D.2)."""

    classify = _classify_step_of(_loader, case.skill)

    async def fake_chat(_system: str, _user: str) -> str:
        return case.expected_choice

    async def explode_runner(_s: str, _u: str) -> AsyncIterator[AgentEvent]:
        raise AssertionError("agent_runner must not be called when llm_chat is wired")
        yield  # pragma: no cover

    inputs: dict[str, Any] = {"user_message": case.user_message}
    outputs = _fixture_outputs_for(case.skill)

    result = await run_llm_classify_step(
        classify,
        inputs,
        outputs,
        llm_chat=fake_chat,
        agent_runner=explode_runner,
    )

    assert result == case.expected_choice, (
        f"pipeline lost label for {case.note!r}: "
        f"expected {case.expected_choice!r}, got {result!r}"
    )


# ---------------------------------------------------------------------------
# Noise-tolerance: same expected label, but the LLM emits a noisy version
# (markdown / explanation / case mismatch / punctuation). _coerce_to_choice
# must still normalise correctly. One case per router skill keeps the
# matrix lean — exhaustive coerce coverage lives in test_meta_mvp.py.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "skill_name, noisy_reply, expected",
    [
        (migration_assistant.SKILL_NAME, "Answer: **VUE2_TO_VUE3**.", "VUE2_TO_VUE3"),
        (migration_assistant.SKILL_NAME, "我认为是 vue2_to_vue3 因为...", "VUE2_TO_VUE3"),
    ],
)
async def test_noisy_llm_reply_still_coerces_to_choice(
    _loader: SkillLoader,
    skill_name: str,
    noisy_reply: str,
    expected: str,
) -> None:
    classify = _classify_step_of(_loader, skill_name)

    async def noisy_chat(_s: str, _u: str) -> str:
        return noisy_reply

    async def explode_runner(_s: str, _u: str) -> AsyncIterator[AgentEvent]:
        raise AssertionError("agent_runner must not be called")
        yield  # pragma: no cover

    result = await run_llm_classify_step(
        classify,
        {"user_message": "ignored — chat is mocked"},
        _fixture_outputs_for(skill_name),
        llm_chat=noisy_chat,
        agent_runner=explode_runner,
    )

    assert result == expected, f"noisy reply {noisy_reply!r} → got {result!r}"
