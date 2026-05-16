from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from opensquilla.skills.hub.installer import InstallResult
from opensquilla.skills.hub.operations import (
    install_loaded_skill_dependency,
    install_skill,
    run_skill_install_operation,
    run_skill_uninstall_operation,
    run_skills_update_operation,
    skill_deps_install_request,
    skill_install_request,
    skill_uninstall_request,
    skills_update_request,
    uninstall_skill,
    update_skills,
)


class FakeInstaller:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []

    async def install(
        self,
        identifier: str,
        source_id: str,
        *,
        force: bool = False,
    ) -> InstallResult:
        self.calls.append(("install", (identifier, source_id), {"force": force}))
        return InstallResult(success=True, name=str(identifier), message="installed")

    async def update(self, name: str | None = None) -> list[InstallResult]:
        self.calls.append(("update", (name,), {}))
        return [InstallResult(success=True, name=name or "all", message="updated")]

    async def uninstall(self, name: str) -> InstallResult:
        self.calls.append(("uninstall", (name,), {}))
        return InstallResult(success=True, name=str(name), message="uninstalled")


class FakeLoader:
    def __init__(self) -> None:
        self.invalidations = 0

    def invalidate_cache(self) -> None:
        self.invalidations += 1


def test_operations_does_not_import_deps_boundary_at_module_load() -> None:
    import opensquilla.skills.hub.operations as hub_operations

    tree = ast.parse(Path(hub_operations.__file__).read_text(encoding="utf-8"))
    top_level_imports = {
        node.module for node in tree.body if isinstance(node, ast.ImportFrom)
    }

    assert "opensquilla.skills.hub.deps" not in top_level_imports


def test_skill_operation_requests_preserve_defaults_and_validation() -> None:
    install_request = skill_install_request({"identifier": "planner"})
    assert install_request.identifier == "planner"
    assert install_request.source_id == "clawhub"
    assert install_request.force is False
    deps_request = skill_deps_install_request({"name": "planner", "install_id": "brew"})
    assert deps_request.name == "planner"
    assert deps_request.install_id == "brew"
    assert skills_update_request(None).name is None
    assert skills_update_request({"name": "planner"}).name == "planner"
    assert skill_uninstall_request({"name": "planner"}).name == "planner"

    with pytest.raises(ValueError, match="params.identifier is required"):
        skill_install_request({})
    with pytest.raises(ValueError, match="params must be a dict"):
        skill_deps_install_request(None)
    with pytest.raises(ValueError, match="params.install_id is required"):
        skill_deps_install_request({"name": "planner"})
    with pytest.raises(ValueError, match="params.name is required"):
        skill_uninstall_request({})


@pytest.mark.asyncio
async def test_skill_operations_delegate_to_installer() -> None:
    installer = FakeInstaller()

    install_result = await install_skill(
        installer,
        skill_install_request(
            {"identifier": "planner", "source": "github", "force": True}
        ),
    )
    update_outcome = await update_skills(
        installer,
        skills_update_request({"name": "planner"}),
    )
    uninstall_result = await uninstall_skill(
        installer,
        skill_uninstall_request({"name": "planner"}),
    )

    assert install_result.success is True
    assert update_outcome.unavailable_message == ""
    assert [result.name for result in update_outcome.results] == ["planner"]
    assert uninstall_result.success is True
    assert installer.calls == [
        ("install", ("planner", "github"), {"force": True}),
        ("update", ("planner",), {}),
        ("uninstall", ("planner",), {}),
    ]


@pytest.mark.asyncio
async def test_update_skills_maps_os_errors_to_unavailable_message() -> None:
    async def fail_update(name: str | None = None) -> list[InstallResult]:
        raise OSError("lockfile unavailable")

    installer = SimpleNamespace(update=fail_update)

    outcome = await update_skills(installer, skills_update_request(None))

    assert outcome.results == []
    assert outcome.unavailable_message == "Skill update unavailable: lockfile unavailable"


@pytest.mark.asyncio
async def test_skill_deps_operation_delegates_to_deps_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.skills.hub import deps

    loader = object()
    calls: list[tuple[object, object]] = []

    async def fake_install_loaded_skill_dependency(
        actual_loader: object,
        request: object,
    ) -> SimpleNamespace:
        calls.append((actual_loader, request))
        return SimpleNamespace(
            result=SimpleNamespace(success=True),
            missing_still={"bins": [], "env": []},
        )

    monkeypatch.setattr(
        deps,
        "install_loaded_skill_dependency",
        fake_install_loaded_skill_dependency,
    )

    request = skill_deps_install_request({"name": "planner", "install_id": "brew"})
    outcome = await install_loaded_skill_dependency(loader, request)

    assert outcome.result.success is True
    assert outcome.missing_still == {"bins": [], "env": []}
    assert calls == [(loader, request)]


@pytest.mark.asyncio
async def test_skill_management_workflows_handle_availability_and_invalidation() -> None:
    loader = FakeLoader()
    installer = FakeInstaller()
    factory_calls: list[str] = []

    def unexpected_factory() -> FakeInstaller:
        factory_calls.append("called")
        return installer

    missing_loader = await run_skill_install_operation(
        None,
        skill_install_request({"identifier": "planner"}),
        installer_factory=unexpected_factory,
    )
    missing_installer = await run_skill_install_operation(
        loader,
        skill_install_request({"identifier": "planner"}),
        installer_factory=lambda: None,
    )
    install_outcome = await run_skill_install_operation(
        loader,
        skill_install_request({"identifier": "planner"}),
        installer_factory=lambda: installer,
    )
    update_outcome = await run_skills_update_operation(
        loader,
        skills_update_request({"name": "planner"}),
        installer_factory=lambda: installer,
    )
    uninstall_outcome = await run_skill_uninstall_operation(
        loader,
        skill_uninstall_request({"name": "planner"}),
        installer_factory=lambda: installer,
    )
    update_missing_loader = await run_skills_update_operation(
        None,
        skills_update_request(None),
        installer_factory=unexpected_factory,
    )
    update_missing_installer = await run_skills_update_operation(
        loader,
        skills_update_request(None),
        installer_factory=lambda: None,
    )
    uninstall_missing_installer = await run_skill_uninstall_operation(
        loader,
        skill_uninstall_request({"name": "planner"}),
        installer_factory=lambda: None,
    )

    assert missing_loader.unavailable_message == "No skill loader configured"
    assert missing_installer.unavailable_message == "No skill installer configured"
    assert install_outcome.result is not None
    assert update_outcome.unavailable_message == ""
    assert uninstall_outcome.result is not None
    assert update_missing_loader.unavailable_message == "No skill loader configured"
    assert update_missing_loader.unavailable_payload == "empty_results"
    assert update_missing_installer.unavailable_message == "No skill installer configured"
    assert update_missing_installer.unavailable_payload == "unavailable"
    assert (
        uninstall_missing_installer.unavailable_message
        == "No skill installer configured"
    )
    assert factory_calls == []
    assert loader.invalidations == 3
