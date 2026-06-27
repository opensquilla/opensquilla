from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from opensquilla.cli.tui.opentui import completion
from opensquilla.cli.tui.opentui.completion import (
    CompletionCandidate,
    build_completion_catalog,
)


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


def test_build_completion_catalog_includes_commands_skills_and_settings() -> None:
    catalog = build_completion_catalog(surface="tui", skill_loader=FakeSkillLoader())
    items = _by_label(catalog)

    assert items["/compact"].category == "command"
    assert items["/compact"].insert_text == "/compact "
    assert items["/compact"].description

    assert items["/code-review"].category == "skill"
    assert items["/code-review"].insert_text == "use the code-review skill: "
    assert "/internal-only" not in items

    assert items["Model"].category == "setting"
    assert items["Model"].insert_text == "/model "
    assert items["Permissions"].insert_text == "/permissions "
    assert items["Cost"].insert_text == "/cost"


def test_build_completion_catalog_keeps_commands_and_settings_when_skill_loader_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_loader(*, workspace_dir: Path | None = None) -> object:
        raise RuntimeError("no config")

    monkeypatch.setattr(completion, "_build_skill_loader", fail_loader)

    catalog = build_completion_catalog(surface="tui")
    items = _by_label(catalog)

    assert items["/compact"].category == "command"
    assert items["Model"].category == "setting"
    assert all(item.category != "skill" for item in catalog)
