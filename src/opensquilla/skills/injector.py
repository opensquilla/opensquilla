"""Injects active skill content into system prompts — full/compact modes."""

from __future__ import annotations

from opensquilla.skills.types import SkillSpec


def _escape_xml(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _skill_location(skill: SkillSpec) -> str:
    if skill.file_path:
        return skill.file_path
    if skill.path is not None:
        return str(skill.path)
    return ""


class SkillInjector:
    """Injects skill content into system prompts with budget control."""

    def inject_full(self, system_prompt: str, skills: list[SkillSpec]) -> str:
        """Full mode: name + description for each skill."""
        visible = [s for s in skills if not s.disable_model_invocation]
        if not visible:
            return system_prompt

        has_meta = any(getattr(s, "kind", "skill") == "meta" for s in visible)
        lines = [
            "\n\n## Skills",
            "Skills are optional task playbooks. Use them only when a listed entry "
            "clearly matches the user's current request.",
            "Skill names are identifiers for `skill_view`; they are not callable tools.",
            "Review <available_skills> before answering.",
            'When one entry is clearly relevant, call skill_view(name="<skill_name>") '
            "to load that skill's instructions, then use only the tools available "
            "in this session.",
        ]
        if has_meta:
            lines.append(
                'Meta-skills (kind="meta"): When a kind="meta" entry clearly matches '
                'and the task benefits from multi-skill orchestration, prefer '
                '`meta_invoke(name="<name>")` over answering directly. Do not call '
                '`skill_view` for kind="meta" entries; call `meta_invoke` directly '
                "without preamble. The framework drives the multi-step DAG; do NOT "
                "call skill_view for sub-skills inside. On success the meta-skill's "
                "deliverable IS the assistant's reply for this turn — no further "
                "commentary needed."
            )
        lines.extend(
            [
                "When no entry is relevant, answer without loading a skill.",
                "",
                "<available_skills>",
            ]
        )
        for s in visible:
            kind = _escape_xml(getattr(s, "kind", "skill"))
            lines.append(f'  <skill kind="{kind}">')
            lines.append(f"    <name>{_escape_xml(s.name)}</name>")
            lines.append(f"    <description>{_escape_xml(s.description)}</description>")
            location = _skill_location(s)
            if location:
                lines.append(f"    <location>{_escape_xml(location)}</location>")
            lines.append("  </skill>")
        lines.append("</available_skills>")
        return system_prompt + "\n".join(lines)

    def inject_compact(self, system_prompt: str, skills: list[SkillSpec]) -> str:
        """Compact mode: name only (saves tokens). Use skill_view to read full content."""
        visible = [s for s in skills if not s.disable_model_invocation]
        if not visible:
            return system_prompt

        has_meta = any(getattr(s, "kind", "skill") == "meta" for s in visible)
        lines = [
            "\n\nSkills are optional task playbooks for specific request types.",
            "Skill names are identifiers for `skill_view`; they are not callable tools.",
            'Call skill_view(name="<skill_name>") only when the current request '
            "matches a listed entry.",
        ]
        if has_meta:
            lines.append(
                'For kind="meta" entries: When a kind="meta" entry clearly matches '
                'and the task benefits from multi-skill orchestration, prefer '
                '`meta_invoke(name="<name>")` over answering directly. Do not call '
                '`skill_view` for kind="meta" entries; call `meta_invoke` directly '
                "without preamble. "
                "The framework runs the DAG and the deliverable is the turn reply."
            )
        lines.extend(["", "<available_skills>"])
        for s in visible:
            kind = _escape_xml(getattr(s, "kind", "skill"))
            lines.append(f'  <skill kind="{kind}">')
            lines.append(f"    <name>{_escape_xml(s.name)}</name>")
            location = _skill_location(s)
            if location:
                lines.append(f"    <location>{_escape_xml(location)}</location>")
            lines.append("  </skill>")
        lines.append("</available_skills>")
        return system_prompt + "\n".join(lines)

    def inject_skills(
        self,
        system_prompt: str,
        skills: list[SkillSpec],
        max_chars: int = 30_000,
    ) -> str:
        """Auto-select full/compact mode based on token budget."""
        if not skills:
            return system_prompt

        full = self.inject_full(system_prompt, skills)
        if len(full) - len(system_prompt) <= max_chars:
            return full

        compact = self.inject_compact(system_prompt, skills)
        if len(compact) - len(system_prompt) <= max_chars:
            return compact

        # Budget exceeded even in compact — truncate skills
        visible = [s for s in skills if not s.disable_model_invocation]
        lo, hi = 0, len(visible)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            test = self.inject_compact(system_prompt, visible[:mid])
            if len(test) - len(system_prompt) <= max_chars:
                lo = mid
            else:
                hi = mid - 1
        # If the safety header itself exceeds an extremely small budget, keep
        # one compact skill entry rather than dropping the whole skills section.
        # Losing the guard makes skill names more likely to be mistaken for tools.
        return self.inject_compact(system_prompt, visible[: max(lo, 1)])
