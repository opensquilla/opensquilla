"""Tests for meta-arxiv-daily-digest-deck (Round-2 linear chain).

Linear chain: fetch_arxiv → digest_papers → render_deck → persist.
Verifies the graceful-skip path when fetch fails.
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
    spec = loader.get_by_name("meta-arxiv-daily-digest-deck")
    assert spec is not None
    plan = parse_meta_plan(spec)
    assert plan is not None

    step_ids = [s.id for s in plan.steps]
    assert step_ids == ["fetch_arxiv", "digest_papers", "render_deck", "persist"]

    by_id = {s.id: s for s in plan.steps}
    assert by_id["digest_papers"].depends_on == ("fetch_arxiv",)
    assert by_id["render_deck"].depends_on == ("digest_papers",)
    # Persist depends on both digest_papers (for content) AND render_deck
    # (for the file path receipt).
    assert set(by_id["persist"].depends_on) == {"digest_papers", "render_deck"}


def _classify(user_message: str) -> str:
    if "Fetch the latest papers from arXiv" in user_message:
        return "fetch_arxiv"
    if "Write a structured digest for each paper" in user_message:
        return "digest_papers"
    if "Render the per-paper digest below into a PPTX" in user_message:
        return "render_deck"
    return "other"


@pytest.mark.asyncio
async def test_happy_path_writes_deck_and_persists(tmp_path: Path) -> None:
    loader = _bundle_loader(tmp_path)
    spec = loader.get_by_name("meta-arxiv-daily-digest-deck")
    plan = parse_meta_plan(spec)
    assert plan is not None

    canned_papers = (
        '[{"id":"2605.0001","title":"Attention Without Attention",'
        '"abstract":"...","authors":["Alice","Bob"],'
        '"pdf_url":"http://example.com/pdf"}]'
    )

    async def runner(_system: str, user_msg: str) -> AsyncIterator[AgentEvent]:
        which = _classify(user_msg)
        if which == "fetch_arxiv":
            yield TextDeltaEvent(text=canned_papers)
        elif which == "digest_papers":
            yield TextDeltaEvent(
                text="## Attention Without Attention\n**Authors**: Alice, Bob\n",
            )
        elif which == "render_deck":
            yield TextDeltaEvent(text="/home/u/.opensquilla/arxiv-daily/digest.pptx")
        else:
            yield TextDeltaEvent(text="memory record saved")
        yield DoneEvent(text="")

    orch = MetaOrchestrator(agent_runner=runner, skill_loader=loader)
    result = await orch.run(
        MetaMatch(plan=plan, inputs={"user_message": "arxiv daily digest"}),
    )
    assert result.ok, f"plan failed: {result.error}"
    assert "Attention" in result.step_outputs["digest_papers"]
    assert result.step_outputs["render_deck"].endswith(".pptx")


@pytest.mark.asyncio
async def test_fetch_failure_propagates_skip_markers(tmp_path: Path) -> None:
    """When fetch_arxiv fails, downstream emits *_SKIPPED markers and the
    plan still completes — no half-baked artefacts."""
    loader = _bundle_loader(tmp_path)
    spec = loader.get_by_name("meta-arxiv-daily-digest-deck")
    plan = parse_meta_plan(spec)
    assert plan is not None

    async def runner(_system: str, user_msg: str) -> AsyncIterator[AgentEvent]:
        which = _classify(user_msg)
        if which == "fetch_arxiv":
            yield TextDeltaEvent(text="FETCH_FAILED: connection refused to export.arxiv.org")
        elif which == "digest_papers":
            yield TextDeltaEvent(text="DIGEST_SKIPPED")
        elif which == "render_deck":
            yield TextDeltaEvent(text="RENDER_SKIPPED")
        else:
            yield TextDeltaEvent(text="memory record saved")
        yield DoneEvent(text="")

    orch = MetaOrchestrator(agent_runner=runner, skill_loader=loader)
    result = await orch.run(
        MetaMatch(plan=plan, inputs={"user_message": "arxiv daily digest"}),
    )
    assert result.ok, f"plan failed: {result.error}"
    assert result.step_outputs["fetch_arxiv"].startswith("FETCH_FAILED")
    assert result.step_outputs["digest_papers"] == "DIGEST_SKIPPED"
    assert result.step_outputs["render_deck"] == "RENDER_SKIPPED"
