from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from opensquilla.skills.loader import SkillLoader
from opensquilla.tools.builtin import skill_tools as skill_tools_module
from opensquilla.tools.registry import get_default_registry


async def _skill_view(name: str, file_path: str | None = None) -> str:
    registered = get_default_registry().get("skill_view")
    assert registered is not None
    return await registered.handler(name=name, file_path=file_path)


@pytest.fixture()
def skill_loader(tmp_path: Path) -> Iterator[SkillLoader]:
    bundled_root = tmp_path / "bundled"
    skill_dir = bundled_root / "deck"
    (skill_dir / "references").mkdir(parents=True)
    (skill_dir / "scripts").mkdir()
    (skill_dir / "assets").mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: deck\ndescription: Deck helper\n---\n"
        "See [guide](references/guide.md).\n",
        encoding="utf-8",
    )
    (skill_dir / "references" / "guide.md").write_text("reference body\n", encoding="utf-8")
    (skill_dir / "scripts" / "inspect.py").write_text("print('script body')\n", encoding="utf-8")
    (skill_dir / "assets" / "palette.txt").write_text("blue\n", encoding="utf-8")
    (skill_dir / "secret.txt").write_text("do not expose\n", encoding="utf-8")

    loader = SkillLoader(
        bundled_dir=bundled_root,
        workspace_dir=tmp_path / "workspace",
        managed_dir=tmp_path / "managed",
        personal_agents_dir=tmp_path / "personal",
        project_agents_dir=tmp_path / "project",
        snapshot_path=tmp_path / "skills.snapshot.json",
    )
    previous_loader = skill_tools_module._loader
    skill_tools_module.create_skill_tools(loader)
    try:
        yield loader
    finally:
        skill_tools_module._loader = previous_loader


@pytest.mark.asyncio
async def test_skill_view_reads_registered_skill_resources_by_relative_path(
    skill_loader: SkillLoader,
) -> None:
    assert "reference body" in await _skill_view("deck", "references/guide.md")
    assert "script body" in await _skill_view("deck", "scripts/inspect.py")
    assert "blue" in await _skill_view("deck", "assets/palette.txt")


@pytest.mark.asyncio
async def test_skill_view_rejects_resource_paths_that_escape_skill_directory(
    skill_loader: SkillLoader,
) -> None:
    result = await _skill_view("deck", "../secret.txt")

    assert "File not found in skill 'deck': ../secret.txt" == result
    assert "do not expose" not in result


@pytest.mark.asyncio
async def test_skill_view_missing_skill_uses_catalog_guidance(
    skill_loader: SkillLoader,
) -> None:
    result = await _skill_view("missing-skill")

    assert "Skill not found: missing-skill" in result
    assert "current skill catalog" in result
    assert "Do not search host filesystem paths" in result
    assert "skill_list" in result
