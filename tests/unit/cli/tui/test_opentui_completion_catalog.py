from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from opensquilla.cli.tui.opentui import completion
from opensquilla.cli.tui.opentui.completion import (
    CompletionCandidate,
    build_completion_catalog,
)
from opensquilla.engine.commands import Surface


@dataclass(frozen=True)
class FakeSkill:
    name: str
    description: str
    disable_model_invocation: bool = False


class FakeSkillLoader:
    def get_user_invocable(self) -> list[FakeSkill]:
        return [
            FakeSkill("code-review", "Review code for regressions."),
            FakeSkill("internal-only", "Hidden from model.", disable_model_invocation=True),
        ]


def _by_label(items: list[CompletionCandidate]) -> dict[str, CompletionCandidate]:
    return {item.label: item for item in items}


def test_build_completion_catalog_includes_commands_and_skills() -> None:
    catalog = build_completion_catalog(surface="tui", skill_loader=FakeSkillLoader())
    items = _by_label(catalog)

    assert items["/compact"].category == "command"
    assert items["/compact"].insert_text == "/compact "
    assert items["/compact"].description

    assert items["/code-review"].category == "skill"
    assert items["/code-review"].insert_text == "use the code-review skill: "
    assert "/internal-only" not in items


def test_build_completion_catalog_dedups_setting_toggles_against_commands() -> None:
    # The gateway surface registry already exposes /model, /permissions, /cost,
    # and /resume; keeping the setting-toggle twins would render each command
    # twice in the slash menu under a second label.
    catalog = build_completion_catalog(
        surface=Surface.CLI_GATEWAY, skill_loader=FakeSkillLoader()
    )
    items = _by_label(catalog)

    assert items["/model"].category == "command"
    assert items["/cost"].category == "command"
    assert "Model" not in items
    assert "Permissions" not in items
    assert "Cost" not in items
    assert "Resume" not in items

    inserts = [candidate.insert_text.strip() for candidate in catalog]
    assert len(inserts) == len(set(inserts)), "duplicate insert targets in catalog"


def test_build_completion_catalog_keeps_toggles_missing_from_surface_registry() -> None:
    # The standalone surface has no /permissions or /resume commands, so those
    # toggles are NOT duplicates there and must survive the dedup.
    catalog = build_completion_catalog(
        surface=Surface.CLI_STANDALONE, skill_loader=FakeSkillLoader()
    )
    items = _by_label(catalog)

    assert items["Permissions"].category == "setting"
    assert items["Resume"].category == "setting"
    assert "Model" not in items  # /model exists on standalone -> deduped
    assert "Cost" not in items  # /cost exists on standalone -> deduped


def test_build_completion_catalog_keeps_commands_and_settings_when_skill_loader_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_loader(*, workspace_dir: Path | None = None) -> object:
        raise RuntimeError("no config")

    monkeypatch.setattr(completion, "_build_skill_loader", fail_loader)

    catalog = build_completion_catalog(surface=Surface.CLI_STANDALONE)
    items = _by_label(catalog)

    assert items["/compact"].category == "command"
    assert items["Permissions"].category == "setting"
    assert all(item.category != "skill" for item in catalog)
