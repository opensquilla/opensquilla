"""Trigger collision: creator vs meta-self-improving-skill-factory vs skill-creator."""

from __future__ import annotations

from pathlib import Path

import pytest

from opensquilla.engine.steps.meta_resolution import _trigger_matches
from opensquilla.skills.loader import SkillLoader

BUNDLED = Path(__file__).resolve().parents[2] / "src" / "opensquilla" / "skills" / "bundled"

CREATOR_TRIGGERS = [
    "新增 meta 技能", "组合现有 skill 成 meta-skill", "synthesize meta-skill", "compose meta-skill",
]
FACTORY_TRIGGERS = ["新增 skill", "create skill", "skill factory", "author a skill"]


@pytest.fixture
def loader(tmp_path):
    sl = SkillLoader(
        bundled_dir=BUNDLED,
        snapshot_path=tmp_path / "collision-snap.json",
    )
    sl.invalidate_cache()
    sl.load_all()
    return sl


def _find_first_match(loader: SkillLoader, text: str) -> str | None:
    text_lower = text.lower()
    matches = []
    for spec in loader.list_meta_specs():
        if any(_trigger_matches(t, text_lower) for t in spec.triggers):
            matches.append(spec)
    if not matches:
        return None
    matches.sort(key=lambda s: s.meta_priority, reverse=True)
    return matches[0].name


def test_creator_triggers_resolve_to_creator(loader) -> None:
    for trig in CREATOR_TRIGGERS:
        assert _find_first_match(loader, trig) == "meta-skill-creator", f"trigger {trig!r}"


def test_factory_triggers_still_resolve_to_factory(loader) -> None:
    for trig in FACTORY_TRIGGERS:
        match = _find_first_match(loader, trig)
        assert match == "meta-self-improving-skill-factory", f"trigger {trig!r} got {match!r}"


def test_factory_wins_on_construct_ambiguous_phrase(loader) -> None:
    """Intentional tie-break: factory (35) > creator (30)."""
    expected = "meta-self-improving-skill-factory"
    assert _find_first_match(loader, "create skill that composes a new meta-skill") == expected


def test_ascii_trigger_does_not_match_meta_skill_explanation_question() -> None:
    assert not _trigger_matches(
        "research report",
        "how does the research report meta-skill work?",
    )
