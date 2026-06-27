"""Meta-skill executors honor the operator gate (codex BLOCKER #2).

A meta-skill that composes ``code-task`` as a step must NOT be able to reach it
while coding mode is off — the gate lives in the executors right after the skill
is resolved from the loader, so it covers both the sub-Agent and wrapped-CLI
(skill_exec) composition styles.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from opensquilla.skills import eligibility
from opensquilla.skills.meta.executors.agent import run_step_with_skill_text_only
from opensquilla.skills.meta.executors.skill_exec import run_skill_exec_step


@pytest.fixture(autouse=True)
def _reset_gate():
    saved = eligibility._live_skills_cfg_getter
    yield
    eligibility.set_live_skills_config_getter(saved)


class _Loader:
    def get_by_name(self, name):
        # Non-None, non-meta spec with NO entrypoint: the operator gate fires
        # before the entrypoint is examined, so a gated skill raises the gate
        # error while an allowed skill falls through to the missing-entrypoint
        # error — letting us distinguish "blocked by gate" from "blocked later".
        return SimpleNamespace(name=name, kind="skill", entrypoint=None)


def _gate(coding_mode: bool, disabled=None):
    eligibility.set_live_skills_config_getter(
        lambda: SimpleNamespace(disabled=disabled or [], coding_mode=coding_mode)
    )


@pytest.mark.asyncio
async def test_skill_exec_step_refuses_gated_codetask():
    _gate(coding_mode=False)
    step = SimpleNamespace(id="s1")
    with pytest.raises(RuntimeError, match="gated by operator config"):
        await run_skill_exec_step(
            step, "code-task", {}, {}, skill_loader=_Loader()
        )


@pytest.mark.asyncio
async def test_text_only_step_refuses_gated_codetask():
    _gate(coding_mode=False)
    step = SimpleNamespace(id="s2")

    async def _llm(_s, _u):  # never reached
        return ""

    with pytest.raises(ValueError, match="gated by operator config"):
        await run_step_with_skill_text_only(
            step, "code-task", {}, {}, llm_chat=_llm, skill_loader=_Loader()
        )


@pytest.mark.asyncio
async def test_executor_allows_other_skill_when_codetask_gated():
    # Gating code-task must not gate an unrelated skill: the gate passes and the
    # step proceeds past the check (then fails later on the absent entrypoint).
    _gate(coding_mode=False)
    step = SimpleNamespace(id="s3")
    with pytest.raises(RuntimeError) as exc:
        await run_skill_exec_step(step, "git-diff", {}, {}, skill_loader=_Loader())
    assert "gated by operator config" not in str(exc.value)
