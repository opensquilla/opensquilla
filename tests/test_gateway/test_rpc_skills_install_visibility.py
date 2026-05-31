from __future__ import annotations

from pathlib import Path

import pytest

from opensquilla.gateway import rpc_skills
from opensquilla.gateway.rpc import RpcContext
from opensquilla.skills.hub.installer import InstallResult
from opensquilla.skills.loader import SkillLoader


@pytest.mark.asyncio
async def test_rpc_skill_install_uses_loader_managed_dir_and_list_sees_skill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    managed_dir = tmp_path / "managed"
    loader = SkillLoader(managed_dir=managed_dir, snapshot_path=tmp_path / "snapshot.json")
    ctx = RpcContext(conn_id="test", skill_loader=loader)
    captured: dict[str, Path | None] = {}

    class FakeInstaller:
        def __init__(self, managed_dir: Path) -> None:
            self.managed_dir = managed_dir

        async def install(
            self,
            identifier: str,
            source_id: str,
            force: bool = False,
        ) -> InstallResult:
            skill_dir = self.managed_dir / identifier
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                "---\n"
                f"name: {identifier}\n"
                "description: Installed from chat\n"
                "---\n"
                "Installed body.\n",
                encoding="utf-8",
            )
            return InstallResult(
                success=True,
                name=identifier,
                message="installed",
                path=str(skill_dir),
            )

    def fake_builder(*, managed_dir: Path | None = None) -> FakeInstaller:
        assert managed_dir is not None
        captured["managed_dir"] = managed_dir
        return FakeInstaller(managed_dir)

    monkeypatch.setattr(rpc_skills, "build_default_skill_installer", fake_builder)
    assert await rpc_skills._handle_skills_list(None, ctx) == {"skills": []}
    assert loader._cached is not None

    installed = await rpc_skills._handle_skills_install(
        {"identifier": "plotter", "source": "clawhub"},
        ctx,
    )
    listed = await rpc_skills._handle_skills_list(None, ctx)

    assert captured["managed_dir"] == managed_dir
    assert installed["success"] is True
    assert Path(installed["path"]).name == "plotter"
    row = next(skill for skill in listed["skills"] if skill["name"] == "plotter")
    assert row["layer"] == "managed"
    assert row["description"] == "Installed from chat"
