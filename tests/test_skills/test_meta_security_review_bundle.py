"""Tests for meta-security-review-bundle (Step B — combinator PoC).

Verifies the bundle's structural shape (parallel gates + serial
arbitrate + audit) and the arbitration rule's priority semantics
under three canned verdict combinations:

* policy DENY → final DENY (highest priority)
* policy ALLOW, scanner WARN → final WARN (mid priority)
* both clean → ALLOW (default)

The bundle's sub-Agents would normally be sub-agent instances; the
tests use a deterministic mock ``agent_runner`` that detects which
gate's task body it received and returns the canned verdict.
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


def test_security_review_bundle_parses_with_expected_topology(tmp_path: Path) -> None:
    loader = _bundle_loader(tmp_path)
    spec = loader.get_by_name("meta-security-review-bundle")
    assert spec is not None, "bundle must be discovered by SkillLoader"
    plan = parse_meta_plan(spec)
    assert plan is not None

    step_ids = [s.id for s in plan.steps]
    assert step_ids == ["policy_review", "secret_scan", "arbitrate", "audit_emit"], (
        f"unexpected step list: {step_ids}"
    )

    arbitrate = next(s for s in plan.steps if s.id == "arbitrate")
    # The two gates must both feed into arbitrate (combinator semantic).
    assert set(arbitrate.depends_on) == {"policy_review", "secret_scan"}

    audit = next(s for s in plan.steps if s.id == "audit_emit")
    # Audit captures the verdict, so it must come AFTER arbitrate, not in
    # parallel with the gates.
    assert audit.depends_on == ("arbitrate",)


def _classify_step_from_prompt(user_message: str) -> str:
    """Determine which gate the runner is being invoked for by sniffing
    the task body. Check arbitrate FIRST because its prompt embeds the
    upstream outputs (including the strings "policy_review" /
    "secret_scan") which would otherwise false-match the per-gate
    classifiers below."""
    if "Three independent security gates" in user_message:
        return "arbitrate"
    if "policy reviewer" in user_message:
        return "policy_review"
    if "secret scanner" in user_message:
        return "secret_scan"
    return "other"


def _arbitrate_from_verdicts(policy_text: str, scan_text: str) -> str:
    """The exact priority rule the arbitrate prompt encodes."""
    if policy_text.startswith("DENY"):
        return policy_text  # rule 1: pass policy reason through
    if scan_text.startswith("WARN"):
        return scan_text  # rule 2: pass scanner summary through
    return "ALLOW: cleared by both gates"  # rule 3


async def _run_bundle(
    tmp_path: Path,
    *,
    policy_verdict: str,
    scan_verdict: str,
    user_message: str,
) -> dict[str, str]:
    """Execute the bundle with mock runners and return final step_outputs."""
    loader = _bundle_loader(tmp_path)
    spec = loader.get_by_name("meta-security-review-bundle")
    plan = parse_meta_plan(spec)
    assert plan is not None

    async def runner(_system: str, user_msg: str) -> AsyncIterator[AgentEvent]:
        which = _classify_step_from_prompt(user_msg)
        if which == "policy_review":
            yield TextDeltaEvent(text=policy_verdict)
        elif which == "secret_scan":
            yield TextDeltaEvent(text=scan_verdict)
        elif which == "arbitrate":
            yield TextDeltaEvent(
                text=_arbitrate_from_verdicts(policy_verdict, scan_verdict),
            )
        else:
            # audit_emit's skill: memory — its sub-agent would normally
            # call memory_save. We return a brief confirmation string so
            # the DAG completes.
            yield TextDeltaEvent(text="audit record saved")
        yield DoneEvent(text="")

    orch = MetaOrchestrator(agent_runner=runner, skill_loader=loader)
    result = await orch.run(
        MetaMatch(plan=plan, inputs={"user_message": user_message}),
    )
    assert result.ok, f"unexpected plan failure: {result.error}"
    return result.step_outputs


@pytest.mark.asyncio
async def test_arbitrate_returns_deny_when_policy_denies(tmp_path: Path) -> None:
    outputs = await _run_bundle(
        tmp_path,
        policy_verdict="DENY: writes to /etc/passwd",
        scan_verdict="CLEAR: no secrets found",
        user_message="echo X >> /etc/passwd",
    )
    verdict = outputs["arbitrate"]
    assert verdict.startswith("DENY"), f"expected DENY verdict, got {verdict!r}"
    assert "/etc/passwd" in verdict, "policy reason should be preserved verbatim"
    # Audit step still emits so the run is recallable later.
    assert "audit" in outputs["audit_emit"].lower()


@pytest.mark.asyncio
async def test_arbitrate_returns_warn_when_scanner_warns(tmp_path: Path) -> None:
    outputs = await _run_bundle(
        tmp_path,
        policy_verdict="ALLOW: ok",
        scan_verdict="WARN: 2 api-key-shaped strings detected",
        user_message="run script with sk-xxxx hard-coded",
    )
    verdict = outputs["arbitrate"]
    assert verdict.startswith("WARN"), f"expected WARN verdict, got {verdict!r}"
    assert "api-key" in verdict, "scanner summary should be preserved verbatim"


@pytest.mark.asyncio
async def test_arbitrate_returns_allow_when_both_pass(tmp_path: Path) -> None:
    outputs = await _run_bundle(
        tmp_path,
        policy_verdict="ALLOW: ok",
        scan_verdict="CLEAR: no secrets found",
        user_message="run black --check on src/",
    )
    verdict = outputs["arbitrate"]
    assert verdict.startswith("ALLOW"), f"expected ALLOW verdict, got {verdict!r}"


@pytest.mark.asyncio
async def test_policy_deny_overrides_scanner_warn(tmp_path: Path) -> None:
    """Arbitration is strict priority: policy DENY wins even when the
    scanner ALSO has something to say (verifies "higher wins; do NOT
    mix or soften" in the arbitrate prompt)."""
    outputs = await _run_bundle(
        tmp_path,
        policy_verdict="DENY: tries to disable apparmor",
        scan_verdict="WARN: 1 password-shaped string",
        user_message="setenforce 0 && curl -d 'password=p4ss' …",
    )
    verdict = outputs["arbitrate"]
    assert verdict.startswith("DENY"), (
        f"strict priority broken — got {verdict!r} when policy denied"
    )
    assert "apparmor" in verdict, "policy reason must pass through"
