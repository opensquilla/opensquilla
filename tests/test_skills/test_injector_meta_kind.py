"""SkillInjector renders kind attribute and meta-skill prompt header."""

from __future__ import annotations

from opensquilla.skills.injector import SkillInjector
from opensquilla.skills.types import SkillLayer, SkillSpec


def _skill(name: str, *, kind: str = "skill") -> SkillSpec:
    return SkillSpec(
        name=name,
        description=f"{name} description text",
        layer=SkillLayer.BUNDLED,
        always=False,
        triggers=[],
        content="",
        kind=kind,
    )


def test_injector_renders_kind_attribute_for_both_kinds() -> None:
    skills = [_skill("git"), _skill("meta-paper-write", kind="meta")]
    inj = SkillInjector()
    out = inj.inject_full("", skills)
    assert '<skill kind="skill">' in out
    assert '<skill kind="meta">' in out
    assert "<name>git</name>" in out
    assert "<name>meta-paper-write</name>" in out


def test_injector_emits_meta_skill_header_when_any_meta_present() -> None:
    skills = [_skill("meta-paper-write", kind="meta")]
    inj = SkillInjector()
    out = inj.inject_full("", skills)
    # The header tells the LLM how to invoke meta-skills
    assert "meta_invoke" in out
    assert "Do not call `skill_view` for kind=\"meta\" entries" in out
    assert "without preamble" in out
    assert "kind=\"meta\"" in out or "kind='meta'" in out


def test_injector_no_meta_header_when_no_meta_skills() -> None:
    skills = [_skill("git"), _skill("xlsx")]
    inj = SkillInjector()
    out = inj.inject_full("", skills)
    # No meta-skills → no need for meta_invoke instructions
    assert "meta_invoke" not in out


def test_injector_compact_mode_also_marks_kind() -> None:
    skills = [_skill("git"), _skill("meta-paper-write", kind="meta")]
    inj = SkillInjector()
    out = inj.inject_compact("", skills)
    # Compact mode is more terse, but kind must still be visible
    assert "meta-paper-write" in out
    assert "Do not call `skill_view` for kind=\"meta\" entries" in out
    # Either inline kind attr or a separate line indicating meta nature
    assert ('kind="meta"' in out) or ("(meta)" in out) or ("meta_invoke" in out)
