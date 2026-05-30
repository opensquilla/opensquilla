"""Tests for meta-pre-commit-quality-gate (Round-2 combinator).

Three quality gates (ruff + mypy + pytest) run in parallel over the
staged diff, then arbitrate a single BLOCK/APPROVE verdict.
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
    spec = loader.get_by_name("meta-pre-commit-quality-gate")
    assert spec is not None
    plan = parse_meta_plan(spec)
    assert plan is not None

    step_ids = [s.id for s in plan.steps]
    assert step_ids == [
        "collect_staged",
        "run_ruff",
        "run_mypy",
        "run_pytest",
        "arbitrate",
        "persist",
    ]

    by_id = {s.id: s for s in plan.steps}
    # Three gates each depend only on collect_staged (parallel).
    for gate in ("run_ruff", "run_mypy", "run_pytest"):
        assert by_id[gate].depends_on == ("collect_staged",), (
            f"gate {gate} should fan out from collect_staged only"
        )
    # Arbitrate gathers all three.
    assert set(by_id["arbitrate"].depends_on) == {"run_ruff", "run_mypy", "run_pytest"}
    # Persist after arbitrate.
    assert by_id["persist"].depends_on == ("arbitrate",)


def _classify(user_message: str) -> str:
    """Map the rendered task body of each step to a stable step id."""
    # Arbitrate has both gate names embedded; check it first.
    if "Three quality gates ran over the staged diff" in user_message:
        return "arbitrate"
    if "git diff --cached --name-only" in user_message:
        return "collect_staged"
    if "ruff check" in user_message:
        return "run_ruff"
    if "mypy --show-error-codes" in user_message:
        return "run_mypy"
    if "pytest -q -x" in user_message:
        return "run_pytest"
    return "other"


def _arbitrate_from(ruff: str, mypy: str, pytest_: str) -> str:
    if any(v.startswith("FAIL") for v in (ruff, mypy, pytest_)):
        fails = [v for v in (ruff, mypy, pytest_) if v.startswith("FAIL")]
        return "BLOCK: " + "; ".join(fails)
    return "APPROVE: ruff/mypy/pytest all green"


async def _run(
    tmp_path: Path,
    *,
    ruff_verdict: str,
    mypy_verdict: str,
    pytest_verdict: str,
    user_message: str = "pre-commit quality gate run",
) -> dict[str, str]:
    loader = _bundle_loader(tmp_path)
    spec = loader.get_by_name("meta-pre-commit-quality-gate")
    plan = parse_meta_plan(spec)
    assert plan is not None

    async def runner(_system: str, user_msg: str) -> AsyncIterator[AgentEvent]:
        which = _classify(user_msg)
        if which == "collect_staged":
            yield TextDeltaEvent(text="src/foo.py\nsrc/opensquilla/bar.py\n")
        elif which == "run_ruff":
            yield TextDeltaEvent(text=ruff_verdict)
        elif which == "run_mypy":
            yield TextDeltaEvent(text=mypy_verdict)
        elif which == "run_pytest":
            yield TextDeltaEvent(text=pytest_verdict)
        elif which == "arbitrate":
            yield TextDeltaEvent(
                text=_arbitrate_from(ruff_verdict, mypy_verdict, pytest_verdict),
            )
        else:
            # persist via memory skill — sub-Agent confirmation
            yield TextDeltaEvent(text="memory record saved")
        yield DoneEvent(text="")

    orch = MetaOrchestrator(agent_runner=runner, skill_loader=loader)
    result = await orch.run(
        MetaMatch(plan=plan, inputs={"user_message": user_message}),
    )
    assert result.ok, f"plan failed: {result.error}"
    return result.step_outputs


@pytest.mark.asyncio
async def test_all_pass_yields_approve(tmp_path: Path) -> None:
    outputs = await _run(
        tmp_path,
        ruff_verdict="PASS: ruff clean",
        mypy_verdict="PASS: mypy clean (or no src files staged)",
        pytest_verdict="PASS: 100 tests passed",
    )
    verdict = outputs["arbitrate"]
    assert verdict.startswith("APPROVE"), f"got {verdict!r}"


@pytest.mark.asyncio
async def test_ruff_fail_yields_block(tmp_path: Path) -> None:
    outputs = await _run(
        tmp_path,
        ruff_verdict="FAIL: 3 findings — E501 line too long; F401 imported but unused",
        mypy_verdict="PASS: mypy clean (or no src files staged)",
        pytest_verdict="PASS: 100 tests passed",
    )
    verdict = outputs["arbitrate"]
    assert verdict.startswith("BLOCK"), f"got {verdict!r}"
    assert "ruff" in verdict.lower() or "E501" in verdict


@pytest.mark.asyncio
async def test_any_fail_blocks(tmp_path: Path) -> None:
    outputs = await _run(
        tmp_path,
        ruff_verdict="PASS: ruff clean",
        mypy_verdict="FAIL: 2 errors — error: missing return type [no-untyped-def]",
        pytest_verdict="PASS: 100 tests passed",
    )
    verdict = outputs["arbitrate"]
    assert verdict.startswith("BLOCK"), f"got {verdict!r}"
    assert "mypy" in verdict.lower() or "no-untyped-def" in verdict
