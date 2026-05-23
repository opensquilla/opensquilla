"""Tests for skills.creator.auto_propose (Path 1+2 library function).

These tests cover the deterministic skeleton — pattern aggregation,
filtering, deduplication, provenance patching, fault tolerance — using
a mock MetaOrchestrator so no LLM calls are required. The LLM-driven
parts of the meta-skill-creator DAG itself are covered by
test_creator_proposer + test_meta_skill_creator_e2e.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from opensquilla.skills.creator.auto_propose import (
    AutoProposeResult,
    auto_propose,
)
from opensquilla.skills.creator.auto_propose import (
    _META_SKILL_CREATOR_TRIGGERS,
    _synthesise_user_message,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _seed_decision_log(
    log_dir: Path,
    chain: list[str],
    *,
    count: int,
    when: datetime | None = None,
) -> None:
    """Append ``count`` decision entries with the given skills chain."""
    when = when or datetime.now(UTC)
    log_dir.mkdir(parents=True, exist_ok=True)
    day = when.strftime("%Y%m%d")
    path = log_dir / f"decisions-{day}.jsonl"
    with path.open("a", encoding="utf-8") as fh:
        for _ in range(count):
            fh.write(json.dumps({
                "ts": when.isoformat(),
                "skills_invoked": list(chain),
            }) + "\n")


def _stub_loader_with_creator(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Build a SkillLoader-shaped mock whose only kind=meta entry is the
    real bundled meta-skill-creator spec (so parse_meta_plan succeeds)."""
    from opensquilla.skills.loader import SkillLoader

    root = Path(__file__).resolve().parents[2]
    real = SkillLoader(
        bundled_dir=root / "src" / "opensquilla" / "skills" / "bundled",
        snapshot_path=root / ".pytest_cache" / "auto_propose_snap.json",
    )
    real.invalidate_cache()
    real.load_all()
    return real  # use the real one — easier than mocking


def _make_proposer_orchestrator(
    proposals_dir: Path,
    *,
    proposal_ids: list[str] | None = None,
    raises: Exception | None = None,
) -> MagicMock:
    """Mock orchestrator whose .run() writes synthetic proposal dirs.

    Mirrors meta-skill-creator's persist step: writes proposal_dir/SKILL.md
    and gates.json for each requested proposal_id, then resolves.
    """
    proposal_ids = list(proposal_ids or [])
    orch = MagicMock()

    async def fake_run(_match: Any) -> Any:
        if raises is not None:
            raise raises
        for pid in proposal_ids:
            d = proposals_dir / pid
            d.mkdir(parents=True, exist_ok=True)
            (d / "SKILL.md").write_text(
                "---\nname: synth-skill\nkind: meta\n---\n", encoding="utf-8",
            )
            (d / "gates.json").write_text(json.dumps({
                "lint": {"G1": {"passed": True}, "G2": {"passed": True}},
                "smoke": {"G3": {"passed": True}, "G4": {"passed": True}},
                "auto_enable_eligible": True,
            }), encoding="utf-8")
        from opensquilla.skills.meta.types import MetaResult
        return MetaResult(ok=True, final_text="ok")

    orch.run = AsyncMock(side_effect=fake_run)
    return orch


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_empty_log_dir_produces_no_proposals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_dir = tmp_path / "logs"
    proposals_dir = tmp_path / "proposals"
    loader = _stub_loader_with_creator(monkeypatch)
    orch = _make_proposer_orchestrator(proposals_dir, proposal_ids=["aaaaaaaa"])

    result = await auto_propose(
        orchestrator=orch,
        skill_loader=loader,
        log_dir=log_dir,
        proposals_dir=proposals_dir,
    )
    assert result.proposals_created == []
    assert result.skipped == []
    assert result.errors == []
    orch.run.assert_not_called()


@pytest.mark.asyncio
async def test_pattern_below_min_freq_is_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_dir = tmp_path / "logs"
    proposals_dir = tmp_path / "proposals"
    _seed_decision_log(log_dir, ["pdf-toolkit", "summarize"], count=2)
    loader = _stub_loader_with_creator(monkeypatch)
    orch = _make_proposer_orchestrator(proposals_dir, proposal_ids=["aaaaaaaa"])

    result = await auto_propose(
        orchestrator=orch,
        skill_loader=loader,
        log_dir=log_dir,
        min_freq=3,
        proposals_dir=proposals_dir,
    )
    assert result.proposals_created == []
    assert len(result.skipped) == 1
    assert result.skipped[0]["reason"] == "below_min_freq"
    orch.run.assert_not_called()


@pytest.mark.asyncio
async def test_pattern_at_threshold_creates_proposal_with_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_dir = tmp_path / "logs"
    proposals_dir = tmp_path / "proposals"
    _seed_decision_log(log_dir, ["nano-pdf", "memory"], count=5)
    loader = _stub_loader_with_creator(monkeypatch)
    orch = _make_proposer_orchestrator(proposals_dir, proposal_ids=["cafe1234"])

    result = await auto_propose(
        orchestrator=orch,
        skill_loader=loader,
        log_dir=log_dir,
        min_freq=3,
        triggered_by="cron",
        proposals_dir=proposals_dir,
    )
    assert result.proposals_created == ["cafe1234"]
    assert result.errors == []
    orch.run.assert_called_once()

    # Provenance was patched onto gates.json
    gates = json.loads((proposals_dir / "cafe1234" / "gates.json").read_text())
    assert gates["provenance"]["triggered_by"] == "auto_cron"
    assert gates["provenance"]["auto_propose_meta"]["skills"] == ["nano-pdf", "memory"]
    assert gates["provenance"]["auto_propose_meta"]["freq"] == 5
    assert isinstance(gates["provenance"]["chain_hash"], str)
    # Lint / smoke payload preserved (provenance is additive, not destructive)
    assert gates["lint"]["G1"]["passed"] is True
    assert gates["auto_enable_eligible"] is True


@pytest.mark.asyncio
async def test_pattern_fully_covered_by_existing_meta_skill_is_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_dir = tmp_path / "logs"
    proposals_dir = tmp_path / "proposals"
    # meta-paper-write already composes paper-experiment-stub + paper-plot-stub
    _seed_decision_log(log_dir, ["paper-experiment-stub", "paper-plot-stub"], count=5)
    loader = _stub_loader_with_creator(monkeypatch)
    orch = _make_proposer_orchestrator(proposals_dir, proposal_ids=["aaaaaaaa"])

    result = await auto_propose(
        orchestrator=orch,
        skill_loader=loader,
        log_dir=log_dir,
        min_freq=3,
        proposals_dir=proposals_dir,
    )
    assert result.proposals_created == []
    assert any(s["reason"] == "already_covered" for s in result.skipped)
    orch.run.assert_not_called()


@pytest.mark.asyncio
async def test_duplicate_pending_proposal_is_skipped_by_chain_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_dir = tmp_path / "logs"
    proposals_dir = tmp_path / "proposals"
    # Pick a chain that no bundled meta-skill composes — otherwise the
    # already_covered branch fires first.
    chain = ["weather", "tmux"]
    _seed_decision_log(log_dir, chain, count=5)
    loader = _stub_loader_with_creator(monkeypatch)

    # Seed a pre-existing proposal carrying the same chain_hash
    from opensquilla.skills.creator.auto_propose import _chain_hash
    existing = proposals_dir / "dead1234"
    existing.mkdir(parents=True)
    (existing / "SKILL.md").write_text("---\nname: dup\nkind: meta\n---\n")
    (existing / "gates.json").write_text(json.dumps({
        "provenance": {"chain_hash": _chain_hash(chain)},
    }))

    orch = _make_proposer_orchestrator(proposals_dir, proposal_ids=["aaaaaaaa"])
    result = await auto_propose(
        orchestrator=orch,
        skill_loader=loader,
        log_dir=log_dir,
        min_freq=3,
        proposals_dir=proposals_dir,
    )
    assert result.proposals_created == []
    assert any(s["reason"] == "duplicate_pending" for s in result.skipped)
    orch.run.assert_not_called()


@pytest.mark.asyncio
async def test_orchestrator_exception_is_collected_not_raised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_dir = tmp_path / "logs"
    proposals_dir = tmp_path / "proposals"
    _seed_decision_log(log_dir, ["nano-pdf", "memory"], count=5)
    loader = _stub_loader_with_creator(monkeypatch)
    orch = _make_proposer_orchestrator(
        proposals_dir, raises=RuntimeError("provider blew up"),
    )

    result = await auto_propose(
        orchestrator=orch,
        skill_loader=loader,
        log_dir=log_dir,
        min_freq=3,
        proposals_dir=proposals_dir,
    )
    assert result.proposals_created == []
    assert len(result.errors) == 1
    assert "provider blew up" in result.errors[0]["error"]


@pytest.mark.asyncio
async def test_asyncio_cancelled_propagates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_dir = tmp_path / "logs"
    proposals_dir = tmp_path / "proposals"
    _seed_decision_log(log_dir, ["nano-pdf", "memory"], count=5)
    loader = _stub_loader_with_creator(monkeypatch)
    orch = _make_proposer_orchestrator(
        proposals_dir, raises=asyncio.CancelledError(),
    )
    with pytest.raises(asyncio.CancelledError):
        await auto_propose(
            orchestrator=orch,
            skill_loader=loader,
            log_dir=log_dir,
            min_freq=3,
            proposals_dir=proposals_dir,
        )


@pytest.mark.asyncio
async def test_dag_produced_no_proposal_is_skipped_not_errored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the meta-skill-creator DAG completes but its lint/smoke gates
    fail mid-DAG (no proposal lands), classify as 'skipped', not error."""
    log_dir = tmp_path / "logs"
    proposals_dir = tmp_path / "proposals"
    _seed_decision_log(log_dir, ["nano-pdf", "memory"], count=5)
    loader = _stub_loader_with_creator(monkeypatch)
    # Empty proposal_ids list — DAG "runs" but writes nothing.
    orch = _make_proposer_orchestrator(proposals_dir, proposal_ids=[])

    result = await auto_propose(
        orchestrator=orch,
        skill_loader=loader,
        log_dir=log_dir,
        min_freq=3,
        proposals_dir=proposals_dir,
    )
    assert result.proposals_created == []
    assert any(s["reason"] == "dag_produced_no_proposal" for s in result.skipped)
    assert result.errors == []


def test_synthesised_user_message_avoids_meta_skill_creator_triggers() -> None:
    """The synth message must NOT contain any meta-skill-creator trigger
    phrase — otherwise auto_propose could recursively trigger itself
    if the synth message were ever fed back into the resolver."""
    msg = _synthesise_user_message(["pdf-toolkit", "summarize"], 5, 30)
    lower = msg.lower()
    for trig in _META_SKILL_CREATOR_TRIGGERS:
        assert trig.lower() not in lower, (
            f"synth message contains trigger {trig!r}: {msg!r}"
        )


def test_summary_string_shape() -> None:
    result = AutoProposeResult(
        proposals_created=["a", "b"],
        skipped=[{"reason": "x"}],
        errors=[{"error": "y"}],
        triggered_by="dream",
    )
    s = result.summary()
    assert "proposals=2" in s
    assert "skipped=1" in s
    assert "errors=1" in s
    assert "via=dream" in s
