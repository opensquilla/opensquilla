"""Templates render and parse cleanly through parse_meta_plan."""

from __future__ import annotations

import tempfile
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from opensquilla.skills.creator.patterns.schemas import (
    FanOutMergeSlots,
    SequentialSlots,
)
from opensquilla.skills.loader import SkillLoader
from opensquilla.skills.meta.parser import parse_meta_plan

TEMPLATES = (
    Path(__file__).resolve().parents[2]
    / "src" / "opensquilla" / "skills" / "creator" / "patterns"
)


def _render_and_parse(template_name: str, slots: dict) -> int:
    env = Environment(loader=FileSystemLoader(TEMPLATES), keep_trailing_newline=True)
    rendered = env.get_template(template_name).render(**slots)

    with tempfile.TemporaryDirectory() as tmp:
        sd = Path(tmp) / "synth"
        sd.mkdir()
        (sd / "SKILL.md").write_text(rendered, encoding="utf-8")
        loader = SkillLoader(bundled_dir=Path(tmp), snapshot_path=Path(tmp) / "snap.json")
        loader.invalidate_cache()
        specs = loader.load_all()
        assert specs, f"no spec loaded; rendered:\n{rendered}"
        plan = parse_meta_plan(specs[0])
        assert plan is not None
        return len(plan.steps)


def test_p1_sequential_renders_and_parses() -> None:
    slots = SequentialSlots(
        name="tst", description="d" * 30, triggers=["go"],
        steps=[
            {"id": "a", "skill": "summarize", "task": "extract"},
            {"id": "b", "skill": "memory", "task": "store"},
        ],
    )
    n = _render_and_parse("p1_sequential.md.j2", slots.model_dump())
    assert n == 2


def test_p2_fan_out_merge_renders_and_parses() -> None:
    slots = FanOutMergeSlots(
        name="tst", description="d" * 30, triggers=["go"],
        branches=[
            {"id": "a", "skill": "weather", "task": "w"},
            {"id": "b", "skill": "summarize", "task": "s"},
        ],
        merge={"id": "m", "skill": "summarize", "task": "merge"},
    )
    n = _render_and_parse("p2_fan_out_merge.md.j2", slots.model_dump())
    assert n == 3


def test_p2_with_tail_renders_4_steps() -> None:
    slots = FanOutMergeSlots(
        name="tst", description="d" * 30, triggers=["go"],
        branches=[
            {"id": "a", "skill": "weather", "task": "w"},
            {"id": "b", "skill": "summarize", "task": "s"},
        ],
        merge={"id": "m", "skill": "summarize", "task": "merge"},
        tail={"id": "save", "skill": "memory", "task": "persist"},
    )
    n = _render_and_parse("p2_fan_out_merge.md.j2", slots.model_dump())
    assert n == 4


def test_p3_condition_gated_renders_and_parses() -> None:
    slots = SequentialSlots(
        name="tst", description="d" * 30, triggers=["go"],
        steps=[
            {"id": "intake", "skill": "summarize", "task": "extract constraints"},
            {"id": "evidence", "skill": "history-explorer", "task": "find context"},
            {"id": "decision", "skill": "summarize", "task": "write decision"},
        ],
    )
    n = _render_and_parse("p3_condition_gated.md.j2", slots.model_dump())
    assert n == 3
