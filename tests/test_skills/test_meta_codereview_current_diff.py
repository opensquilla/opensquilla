"""Tests for meta-codereview-current-diff (Round-2 combinator).

Three independent reviewers (safety + tests + style) run in parallel
over the diff; arbitrate applies strict priority CRITICAL > WARNING/
MISSING > clean.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from opensquilla.engine.types import AgentEvent, DoneEvent, TextDeltaEvent
from opensquilla.skills.loader import SkillLoader
from opensquilla.skills.meta.orchestrator import MetaOrchestrator
from opensquilla.skills.meta.parser import parse_meta_plan
from opensquilla.skills.meta.types import MetaMatch

_BUNDLED = (
    Path(__file__).resolve().parents[2] / "src" / "opensquilla" / "skills" / "bundled"
)
_EXP = Path(__file__).resolve().parents[2] / "src" / "opensquilla" / "skills" / "exp"


def _bundle_loader(tmp_path: Path) -> SkillLoader:
    loader = SkillLoader(
        bundled_dir=_BUNDLED,
        extra_dirs=[_EXP],
        snapshot_path=tmp_path / "snap.json",
    )
    loader.invalidate_cache()
    loader.load_all()
    return loader


def test_parses_with_expected_topology(tmp_path: Path) -> None:
    loader = _bundle_loader(tmp_path)
    spec = loader.get_by_name("meta-codereview-current-diff")
    assert spec is not None
    plan = parse_meta_plan(spec)
    assert plan is not None

    step_ids = [s.id for s in plan.steps]
    assert step_ids == [
        "read_diff",
        "review_safety",
        "review_tests",
        "review_style",
        "arbitrate",
        "persist",
    ]
    by_id = {s.id: s for s in plan.steps}
    for r in ("review_safety", "review_tests", "review_style"):
        assert by_id[r].depends_on == ("read_diff",)
    assert set(by_id["arbitrate"].depends_on) == {
        "review_safety",
        "review_tests",
        "review_style",
    }
    assert by_id["persist"].depends_on == ("arbitrate",)


def _classify(user_message: str) -> str:
    # Arbitrate first (embeds the per-reviewer step ids).
    if "Three reviewers ran on the diff" in user_message:
        return "arbitrate"
    if "git diff --cached HEAD" in user_message:
        return "read_diff"
    if "safety reviewer" in user_message:
        return "review_safety"
    if "test-coverage reviewer" in user_message:
        return "review_tests"
    if "style / idiom reviewer" in user_message:
        return "review_style"
    return "other"


def _arbitrate(safety: str, tests: str, style: str) -> str:
    if safety.startswith("CRITICAL"):
        return f"BLOCK: {safety}"
    if safety.startswith("WARNING") or tests.startswith("MISSING_TESTS"):
        bits = []
        if safety.startswith("WARNING"):
            bits.append(safety)
        if tests.startswith("MISSING_TESTS"):
            bits.append(tests)
        return f"BLOCK_WITH_OVERRIDE: {'; '.join(bits)}"
    note = style if style.startswith("ANTIPATTERNS") else "clean"
    return f"PASS_WITH_NOTES: {note}"


async def _run(
    tmp_path: Path,
    *,
    safety_verdict: str,
    tests_verdict: str,
    style_verdict: str,
    user_message: str = "multi-reviewer diff",
) -> dict[str, str]:
    loader = _bundle_loader(tmp_path)
    spec = loader.get_by_name("meta-codereview-current-diff")
    plan = parse_meta_plan(spec)
    assert plan is not None

    async def runner(_system: str, user_msg: str) -> AsyncIterator[AgentEvent]:
        which = _classify(user_msg)
        if which == "read_diff":
            yield TextDeltaEvent(
                text="diff --git a/foo.py b/foo.py\n+def new_public():\n+    pass\n",
            )
        elif which == "review_safety":
            yield TextDeltaEvent(text=safety_verdict)
        elif which == "review_tests":
            yield TextDeltaEvent(text=tests_verdict)
        elif which == "review_style":
            yield TextDeltaEvent(text=style_verdict)
        elif which == "arbitrate":
            yield TextDeltaEvent(
                text=_arbitrate(safety_verdict, tests_verdict, style_verdict),
            )
        else:
            yield TextDeltaEvent(text="memory record saved")
        yield DoneEvent(text="")

    orch = MetaOrchestrator(agent_runner=runner, skill_loader=loader)
    result = await orch.run(
        MetaMatch(plan=plan, inputs={"user_message": user_message}),
    )
    assert result.ok, f"plan failed: {result.error}"
    return result.step_outputs


@pytest.mark.asyncio
async def test_safety_critical_blocks(tmp_path: Path) -> None:
    outputs = await _run(
        tmp_path,
        safety_verdict="CRITICAL: SQL injection via f-string in user_query",
        tests_verdict="PASS: tests adequate",
        style_verdict="CLEAN: no style issues found",
    )
    verdict = outputs["arbitrate"]
    assert verdict.startswith("BLOCK:"), f"got {verdict!r}"
    assert "SQL injection" in verdict


@pytest.mark.asyncio
async def test_missing_tests_block_with_override(tmp_path: Path) -> None:
    outputs = await _run(
        tmp_path,
        safety_verdict="CLEAR: no safety concerns found",
        tests_verdict="MISSING_TESTS: new_public lacks tests",
        style_verdict="CLEAN: no style issues found",
    )
    verdict = outputs["arbitrate"]
    assert verdict.startswith("BLOCK_WITH_OVERRIDE"), f"got {verdict!r}"
    assert "new_public" in verdict


@pytest.mark.asyncio
async def test_all_clean_pass_with_notes(tmp_path: Path) -> None:
    outputs = await _run(
        tmp_path,
        safety_verdict="CLEAR: no safety concerns found",
        tests_verdict="PASS: tests adequate",
        style_verdict="CLEAN: no style issues found",
    )
    verdict = outputs["arbitrate"]
    assert verdict.startswith("PASS_WITH_NOTES"), f"got {verdict!r}"


@pytest.mark.asyncio
async def test_safety_critical_overrides_missing_tests(tmp_path: Path) -> None:
    """Strict priority: safety CRITICAL wins over tests MISSING_TESTS."""
    outputs = await _run(
        tmp_path,
        safety_verdict="CRITICAL: hardcoded credential sk-xxxx",
        tests_verdict="MISSING_TESTS: tests not added",
        style_verdict="ANTIPATTERNS: bare except at foo.py:12",
    )
    verdict = outputs["arbitrate"]
    assert verdict.startswith("BLOCK:"), f"got {verdict!r}"
    assert "sk-xxxx" in verdict
