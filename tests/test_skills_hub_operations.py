from __future__ import annotations

from types import SimpleNamespace

import pytest

from opensquilla.skills.hub.installer import InstallResult
from opensquilla.skills.hub.operations import (
    install_skill,
    run_skill_install_operation,
    run_skill_uninstall_operation,
    run_skills_update_operation,
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


def test_skill_operation_requests_preserve_defaults_and_validation() -> None:
    install_request = skill_install_request({"identifier": "planner"})
    assert install_request.identifier == "planner"
    assert install_request.source_id == "clawhub"
    assert install_request.force is False
    assert skills_update_request(None).name is None
    assert skills_update_request({"name": "planner"}).name == "planner"
    assert skill_uninstall_request({"name": "planner"}).name == "planner"

    with pytest.raises(ValueError, match="params.identifier is required"):
        skill_install_request({})
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
async def test_skill_management_workflows_handle_availability_and_invalidation() -> None:
    loader = FakeLoader()
    installer = FakeInstaller()

    missing_loader = await run_skill_install_operation(
        None,
        lambda: installer,
        skill_install_request({"identifier": "planner"}),
    )
    missing_installer = await run_skill_install_operation(
        loader,
        lambda: None,
        skill_install_request({"identifier": "planner"}),
    )
    install_outcome = await run_skill_install_operation(
        loader,
        lambda: installer,
        skill_install_request({"identifier": "planner"}),
    )
    update_outcome = await run_skills_update_operation(
        loader,
        lambda: installer,
        skills_update_request({"name": "planner"}),
    )
    uninstall_outcome = await run_skill_uninstall_operation(
        loader,
        lambda: installer,
        skill_uninstall_request({"name": "planner"}),
    )
    update_missing_loader = await run_skills_update_operation(
        None,
        lambda: installer,
        skills_update_request(None),
    )
    update_missing_installer = await run_skills_update_operation(
        loader,
        lambda: None,
        skills_update_request(None),
    )
    uninstall_missing_installer = await run_skill_uninstall_operation(
        loader,
        lambda: None,
        skill_uninstall_request({"name": "planner"}),
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
    assert loader.invalidations == 3
