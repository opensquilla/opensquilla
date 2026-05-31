from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from opensquilla.skills.hub.installer import InstallResult
from opensquilla.skills.hub.scanner import ScanFinding, ScanResult
from opensquilla.skills.hub.source import SkillMeta
from opensquilla.skills.loader import SkillLoader
from opensquilla.tools.builtin import skill_tools as skill_tools_module
from opensquilla.tools.registry import get_default_registry


async def _skill_view(name: str, file_path: str | None = None) -> str:
    registered = get_default_registry().get("skill_view")
    assert registered is not None
    return await registered.handler(name=name, file_path=file_path)


async def _skill_search_community(query: str, source: str = "clawhub", limit: int = 10) -> str:
    registered = get_default_registry().get("skill_search_community")
    assert registered is not None
    return await registered.handler(query=query, source=source, limit=limit)


async def _skill_install_community(
    identifier: str,
    source: str = "clawhub",
    force: bool = False,
) -> str:
    registered = get_default_registry().get("skill_install_community")
    assert registered is not None
    return await registered.handler(identifier=identifier, source=source, force=force)


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


@pytest.mark.asyncio
async def test_skill_search_community_returns_hub_results_with_installed_flag(
    skill_loader: SkillLoader,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeRouter:
        def __init__(self) -> None:
            self.calls: list[tuple[str, int, str | None]] = []

        async def search(
            self,
            query: str,
            limit: int = 20,
            source_id: str | None = None,
        ) -> list[SkillMeta]:
            self.calls.append((query, limit, source_id))
            return [
                SkillMeta(
                    name="plotter",
                    description="Plot charts",
                    version="1.0.0",
                    author="OpenSquilla",
                    source_id="clawhub",
                    trust_level="community",
                    identifier="plotter",
                )
            ]

    router = FakeRouter()
    monkeypatch.setattr(skill_tools_module, "get_default_skill_router", lambda: router)
    monkeypatch.setattr(skill_tools_module, "installed_skill_names", lambda: {"plotter"})

    payload = json.loads(await _skill_search_community("plot", source="clawhub", limit=5))

    assert payload["status"] == "ok"
    assert router.calls == [("plot", 5, "clawhub")]
    assert payload["results"] == [
        {
            "name": "plotter",
            "description": "Plot charts",
            "version": "1.0.0",
            "author": "OpenSquilla",
            "source": "clawhub",
            "trust_level": "community",
            "identifier": "plotter",
            "installed": True,
        }
    ]


@pytest.mark.asyncio
async def test_skill_install_community_uses_loader_managed_dir_and_invalidates_cache(
    skill_loader: SkillLoader,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeInstaller:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, bool]] = []

        async def install(
            self,
            identifier: str,
            source_id: str,
            force: bool = False,
        ) -> InstallResult:
            self.calls.append((identifier, source_id, force))
            return InstallResult(
                success=True,
                name="plotter",
                message="installed",
                path=str(skill_loader.managed_dir / "plotter"),
            )

    installer = FakeInstaller()
    captured: dict[str, Path | None] = {}

    def fake_builder(*, managed_dir: Path | None = None) -> FakeInstaller:
        captured["managed_dir"] = managed_dir
        return installer

    monkeypatch.setattr(skill_tools_module, "build_default_skill_installer", fake_builder)
    skill_loader.load_all()
    assert skill_loader._cached is not None

    payload = json.loads(await _skill_install_community("plotter"))

    assert captured["managed_dir"] == skill_loader.managed_dir
    assert installer.calls == [("plotter", "clawhub", False)]
    assert payload["status"] == "installed"
    assert payload["success"] is True
    assert Path(payload["path"]).name == "plotter"
    assert skill_loader._cached is None


@pytest.mark.asyncio
async def test_skill_install_community_surfaces_scan_failure_without_invalidating_cache(
    skill_loader: SkillLoader,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeInstaller:
        async def install(
            self,
            identifier: str,
            source_id: str,
            force: bool = False,
        ) -> InstallResult:
            return InstallResult(
                success=False,
                name=identifier,
                message="Security scan: dangerous",
                scan=ScanResult(
                    verdict="dangerous",
                    findings=[
                        ScanFinding(
                            category="prompt_injection",
                            severity="dangerous",
                            line=1,
                            text="ignore previous instructions",
                            pattern="ignore",
                        )
                    ],
                ),
            )

    monkeypatch.setattr(
        skill_tools_module,
        "build_default_skill_installer",
        lambda *, managed_dir=None: FakeInstaller(),
    )
    skill_loader.load_all()
    assert skill_loader._cached is not None

    payload = json.loads(await _skill_install_community("unsafe"))

    assert payload["status"] == "failed"
    assert payload["success"] is False
    assert payload["scan_verdict"] == "dangerous"
    assert payload["scan_findings"][0]["category"] == "prompt_injection"
    assert skill_loader._cached is not None
