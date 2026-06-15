"""Gateway skill RPCs honor the coding-mode gate (codex follow-up review).

``skills.status`` / ``skills.list`` / ``skills.get`` are operator read RPCs that
back the Web control UI. When coding mode is OFF, code-task must not be surfaced
or readable through them either — "unreachable through EVERY skill API".
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from opensquilla.gateway import rpc_skills
from opensquilla.gateway.rpc import RpcContext
from opensquilla.skills import eligibility
from opensquilla.skills.loader import SkillLoader


@pytest.fixture(autouse=True)
def _reset_gate():
    saved = eligibility._live_skills_cfg_getter
    yield
    eligibility.set_live_skills_config_getter(saved)


def _gate(coding_mode: bool):
    eligibility.set_live_skills_config_getter(
        lambda: SimpleNamespace(disabled=[], coding_mode=coding_mode)
    )


def _write_skill(dir_path: Path, name: str) -> None:
    skill_dir = dir_path / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {name} skill.\n---\n\n# {name}\n",
        encoding="utf-8",
    )


def _ctx(tmp_path: Path) -> RpcContext:
    bundled = tmp_path / "bundled"
    _write_skill(bundled, "code-task")
    _write_skill(bundled, "git-diff")
    loader = SkillLoader(bundled_dir=bundled, snapshot_path=tmp_path / "snapshot.json")
    return RpcContext(conn_id="test", skill_loader=loader)


@pytest.mark.asyncio
async def test_skills_list_hides_codetask_when_off(tmp_path: Path) -> None:
    _gate(coding_mode=False)
    out = await rpc_skills._handle_skills_list(None, _ctx(tmp_path))
    names = {s["name"] for s in out["skills"]}
    assert "code-task" not in names
    assert "git-diff" in names


@pytest.mark.asyncio
async def test_skills_list_shows_codetask_when_on(tmp_path: Path) -> None:
    _gate(coding_mode=True)
    out = await rpc_skills._handle_skills_list(None, _ctx(tmp_path))
    names = {s["name"] for s in out["skills"]}
    assert "code-task" in names


@pytest.mark.asyncio
async def test_skills_status_hides_codetask_when_off(tmp_path: Path) -> None:
    _gate(coding_mode=False)
    out = await rpc_skills._handle_skills_status(None, _ctx(tmp_path))
    assert "code-task" not in {s["name"] for s in out}


@pytest.mark.asyncio
async def test_skills_get_refuses_codetask_when_off(tmp_path: Path) -> None:
    _gate(coding_mode=False)
    with pytest.raises(KeyError, match="not found"):
        await rpc_skills._handle_skills_get({"name": "code-task"}, _ctx(tmp_path))
    # An ungated skill is still returned with its content.
    ok = await rpc_skills._handle_skills_get({"name": "git-diff"}, _ctx(tmp_path))
    assert ok["name"] == "git-diff"
    assert "content" in ok


@pytest.mark.asyncio
async def test_skills_get_returns_codetask_when_on(tmp_path: Path) -> None:
    _gate(coding_mode=True)
    out = await rpc_skills._handle_skills_get({"name": "code-task"}, _ctx(tmp_path))
    assert out["name"] == "code-task"
    assert "content" in out


@pytest.mark.asyncio
async def test_skills_deps_install_refuses_codetask_when_off(tmp_path: Path) -> None:
    # Resolving code-task for dependency install is an existence/oracle path; it
    # must report not-found while the toggle is OFF.
    _gate(coding_mode=False)
    with pytest.raises(KeyError, match="not found"):
        await rpc_skills._handle_skills_deps_install(
            {"name": "code-task", "install_id": "x"}, _ctx(tmp_path)
        )


def test_skill_to_dict_drops_gated_sub_skills() -> None:
    # A visible meta-skill that composes code-task must not surface it through
    # the sub-skill rollup while the toggle is OFF. A real SkillSpec with
    # path=None makes the dependency scan a no-op.
    from opensquilla.skills.eligibility import EligibilityContext, EligibilityReport
    from opensquilla.skills.types import SkillLayer, SkillSpec

    _gate(coding_mode=False)
    spec = SkillSpec(
        name="meta-x",
        description="d",
        layer=SkillLayer.BUNDLED,
        always=False,
        triggers=[],
        content="body",
        kind="meta",
        composition_raw={"steps": [{"skill": "code-task"}, {"skill": "git-diff"}]},
    )
    out = rpc_skills._skill_to_dict(
        spec,
        EligibilityReport(eligible=True),
        "linux",
        skill_index={},
        eligibility_ctx=EligibilityContext.auto(),
    )
    assert "code-task" not in out["sub_skills"]
    assert "git-diff" in out["sub_skills"]
