from __future__ import annotations

from types import SimpleNamespace

import pytest

from opensquilla.skills.hub import deps
from opensquilla.skills.hub.deps import (
    DepResult,
    install_loaded_skill_dependency,
    install_skill_dependency,
    skill_deps_install_request,
)
from opensquilla.skills.types import SkillInstallSpec, SkillPlatformMeta


@pytest.mark.asyncio
async def test_install_skill_dependency_selects_spec_and_reports_remaining_gaps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected_spec = SkillInstallSpec(id="brew", kind="brew", os=[])
    ignored_spec = SkillInstallSpec(id="uv", kind="uv", os=[])
    skill = SimpleNamespace(
        metadata=SkillPlatformMeta(install=[ignored_spec, selected_spec])
    )
    installed_specs: list[SkillInstallSpec] = []
    validated: list[tuple[SkillInstallSpec, str]] = []

    async def fake_install_deps(specs: list[SkillInstallSpec]) -> list[DepResult]:
        installed_specs.extend(specs)
        return [DepResult(kind="brew", identifier="brew", success=True, message="installed")]

    monkeypatch.setattr(deps, "install_deps", fake_install_deps)
    monkeypatch.setattr(
        deps,
        "validate_skill_install_supported",
        lambda spec, install_id: validated.append((spec, install_id)),
    )
    monkeypatch.setattr(
        deps,
        "skill_missing_requirements",
        lambda actual_skill: {"bins": ["node"], "env": []},
    )

    outcome = await install_skill_dependency(skill, name="planner", install_id="brew")

    assert installed_specs == [selected_spec]
    assert validated == [(selected_spec, "brew")]
    assert outcome.result.success is True
    assert outcome.result.kind == "brew"
    assert outcome.missing_still == {"bins": ["node"], "env": []}


@pytest.mark.asyncio
async def test_install_skill_dependency_raises_for_unknown_install_id() -> None:
    skill = SimpleNamespace(metadata=SkillPlatformMeta(install=[]))

    with pytest.raises(KeyError, match="Install spec not found: brew"):
        await install_skill_dependency(skill, name="planner", install_id="brew")


def test_skill_deps_install_request_validates_required_fields() -> None:
    request = skill_deps_install_request({"name": "planner", "install_id": "brew"})

    assert request.name == "planner"
    assert request.install_id == "brew"

    with pytest.raises(ValueError, match="params must be a dict"):
        skill_deps_install_request(None)
    with pytest.raises(ValueError, match="params.name is required"):
        skill_deps_install_request({})
    with pytest.raises(ValueError, match="params.install_id is required"):
        skill_deps_install_request({"name": "planner"})


@pytest.mark.asyncio
async def test_install_loaded_skill_dependency_resolves_skill_from_loader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    skill = SimpleNamespace(metadata=SkillPlatformMeta(install=[]))
    loader = SimpleNamespace(get_by_name=lambda name: skill if name == "planner" else None)
    calls: list[tuple[object, str, str]] = []

    async def fake_install_skill_dependency(
        actual_skill: object,
        *,
        name: str,
        install_id: str,
    ) -> SimpleNamespace:
        calls.append((actual_skill, name, install_id))
        return SimpleNamespace(
            result=DepResult(kind="brew", identifier="brew", success=True),
            missing_still={"bins": [], "env": []},
        )

    monkeypatch.setattr(deps, "install_skill_dependency", fake_install_skill_dependency)

    outcome = await install_loaded_skill_dependency(
        loader,
        skill_deps_install_request({"name": "planner", "install_id": "brew"}),
    )

    assert calls == [(skill, "planner", "brew")]
    assert outcome.result.success is True
    assert outcome.missing_still == {"bins": [], "env": []}


@pytest.mark.asyncio
async def test_install_loaded_skill_dependency_raises_when_loader_or_skill_missing() -> None:
    request = skill_deps_install_request({"name": "planner", "install_id": "brew"})

    with pytest.raises(KeyError, match="No skill loader available"):
        await install_loaded_skill_dependency(None, request)
    with pytest.raises(KeyError, match="Skill not found: planner"):
        await install_loaded_skill_dependency(
            SimpleNamespace(get_by_name=lambda _name: None),
            request,
        )
