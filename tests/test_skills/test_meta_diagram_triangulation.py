"""Tests for meta-diagram-triangulation (Round-2 classifier + parallel render).

scan → llm_classify(diagram_kind) → parallel { plantuml | drawio } →
compose docx → persist.
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
    spec = loader.get_by_name("meta-diagram-triangulation")
    assert spec is not None
    plan = parse_meta_plan(spec)
    assert plan is not None

    step_ids = [s.id for s in plan.steps]
    assert step_ids == [
        "scan_repo",
        "classify_kind",
        "render_plantuml",
        "render_drawio",
        "compose_doc",
        "persist",
    ]

    by_id = {s.id: s for s in plan.steps}
    assert by_id["classify_kind"].depends_on == ("scan_repo",)
    # llm_classify must declare output_choices.
    assert by_id["classify_kind"].kind == "llm_classify"
    assert set(by_id["classify_kind"].output_choices) == {
        "class", "sequence", "component", "deploy", "flow",
    }
    # Two render branches fan out from scan + classify.
    for r in ("render_plantuml", "render_drawio"):
        assert set(by_id[r].depends_on) == {"scan_repo", "classify_kind"}
    # compose_doc gathers both renders.
    assert set(by_id["compose_doc"].depends_on) == {"render_plantuml", "render_drawio"}
    assert by_id["persist"].depends_on == ("compose_doc",)


def _classify_step(system: str, user_message: str) -> str:
    """Map a runner invocation to a stable step id."""
    # llm_classify uses a known classifier system prompt.
    if "deterministic classifier" in (system or "").lower():
        return "classify_kind"
    if "Scan the target path identified" in user_message:
        return "scan_repo"
    if "Generate a PlantUML diagram source" in user_message:
        return "render_plantuml"
    if "Generate a draw.io XML diagram" in user_message:
        return "render_drawio"
    if "Compose an architecture document" in user_message:
        return "compose_doc"
    return "other"


@pytest.mark.asyncio
async def test_happy_path_runs_all_steps(tmp_path: Path) -> None:
    loader = _bundle_loader(tmp_path)
    spec = loader.get_by_name("meta-diagram-triangulation")
    plan = parse_meta_plan(spec)
    assert plan is not None

    async def runner(_system: str, user_msg: str) -> AsyncIterator[AgentEvent]:
        which = _classify_step(_system, user_msg)
        if which == "scan_repo":
            yield TextDeltaEvent(
                text=(
                    "## Target path\n/home/u/repo/src/foo\n"
                    "## Modules (top-level)\n- foo/: data layer\n"
                    "## Dependencies\nfoo → bar\n"
                ),
            )
        elif which == "classify_kind":
            # Classifier must emit one of the declared choices.
            yield TextDeltaEvent(text="component")
        elif which == "render_plantuml":
            yield TextDeltaEvent(text="/home/u/.opensquilla/diagrams/arch.puml")
        elif which == "render_drawio":
            yield TextDeltaEvent(text="/home/u/.opensquilla/diagrams/arch.drawio")
        elif which == "compose_doc":
            yield TextDeltaEvent(text="/home/u/.opensquilla/diagrams/arch.docx")
        else:
            yield TextDeltaEvent(text="memory record saved")
        yield DoneEvent(text="")

    orch = MetaOrchestrator(agent_runner=runner, skill_loader=loader)
    result = await orch.run(
        MetaMatch(
            plan=plan,
            inputs={"user_message": "diagram triangulation for src/opensquilla/skills/meta/"},
        ),
    )
    assert result.ok, f"plan failed: {result.error}"
    # The two renders ran (proves parallel fan-out completed).
    assert result.step_outputs["render_plantuml"].endswith(".puml")
    assert result.step_outputs["render_drawio"].endswith(".drawio")
    # The classifier returned a valid choice.
    assert result.step_outputs["classify_kind"] == "component"
    # The compose step is downstream of both — proves fan-in.
    assert result.step_outputs["compose_doc"].endswith(".docx")


@pytest.mark.asyncio
async def test_classifier_choice_propagates_to_render_prompts(tmp_path: Path) -> None:
    """Verify the chosen diagram_kind reaches both render prompts via
    Jinja template substitution."""
    loader = _bundle_loader(tmp_path)
    spec = loader.get_by_name("meta-diagram-triangulation")
    plan = parse_meta_plan(spec)
    assert plan is not None

    seen_render_prompts: dict[str, str] = {}

    async def runner(_system: str, user_msg: str) -> AsyncIterator[AgentEvent]:
        which = _classify_step(_system, user_msg)
        if which == "scan_repo":
            yield TextDeltaEvent(text="scan output")
        elif which == "classify_kind":
            yield TextDeltaEvent(text="sequence")
        elif which == "render_plantuml":
            seen_render_prompts["plantuml"] = user_msg
            yield TextDeltaEvent(text="/tmp/arch.puml")
        elif which == "render_drawio":
            seen_render_prompts["drawio"] = user_msg
            yield TextDeltaEvent(text="/tmp/arch.drawio")
        elif which == "compose_doc":
            yield TextDeltaEvent(text="/tmp/arch.docx")
        else:
            yield TextDeltaEvent(text="saved")
        yield DoneEvent(text="")

    orch = MetaOrchestrator(agent_runner=runner, skill_loader=loader)
    result = await orch.run(
        MetaMatch(plan=plan, inputs={"user_message": "diagram triangulation"}),
    )
    assert result.ok
    # Classifier output substituted into both render prompts.
    assert "kind `sequence`" in seen_render_prompts["plantuml"], (
        f"plantuml prompt missing kind substitution: {seen_render_prompts['plantuml'][:200]}"
    )
    assert "kind `sequence`" in seen_render_prompts["drawio"], (
        f"drawio prompt missing kind substitution: {seen_render_prompts['drawio'][:200]}"
    )
