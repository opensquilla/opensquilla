from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from opensquilla.skills.hub.installer import InstallResult
from opensquilla.skills.hub.operations import (
    add_tap,
    default_skill_installer_factory,
    default_skill_router_factory,
    default_taps_manager_factory,
    install_loaded_skill_dependency,
    install_skill,
    list_taps,
    publish_skill_from_request,
    remove_tap,
    run_skill_install_operation,
    run_skill_uninstall_operation,
    run_skills_update_operation,
    search_skills,
    skill_deps_install_request,
    skill_install_request,
    skill_publish_request,
    skill_search_request,
    skill_uninstall_request,
    skills_update_request,
    tap_add_request,
    tap_remove_request,
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
    assert "opensquilla.skills.hub.defaults" not in top_level_imports
    assert "opensquilla.skills.hub.installer" not in top_level_imports
    assert "opensquilla.skills.hub.lockfile" not in top_level_imports
    assert "opensquilla.skills.hub.publisher" not in top_level_imports
    assert "opensquilla.skills.hub.taps" not in top_level_imports


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


def test_skill_publish_request_delegates_to_publisher_request(tmp_path: Path) -> None:
    request = skill_publish_request(
        {"skill_dir": tmp_path / "demo-skill", "repo": "acme/skills"}
    )

    assert request.skill_dir == tmp_path / "demo-skill"
    assert request.target_repo == "acme/skills"


def test_tap_operation_requests_preserve_validation() -> None:
    add_request = tap_add_request({"owner_repo": "acme/tap"})
    remove_request = tap_remove_request({"owner_repo": "acme/tap"})

    assert add_request.owner_repo == "acme/tap"
    assert remove_request.owner_repo == "acme/tap"

    with pytest.raises(ValueError, match="params.owner_repo is required"):
        tap_add_request({})
    with pytest.raises(ValueError, match="params.owner_repo is required"):
        tap_remove_request({})


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
async def test_search_skills_delegates_to_default_router_and_lockfile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.skills.hub import defaults, lockfile

    calls: list[tuple[str, object]] = []

    class FakeRouter:
        async def search(
            self,
            query: object,
            *,
            limit: int,
            source_id: str | None,
        ) -> list[SimpleNamespace]:
            calls.append(("search", (query, limit, source_id)))
            return [SimpleNamespace(name="planner")]

    router = FakeRouter()
    monkeypatch.setattr(
        defaults,
        "get_default_skill_router",
        lambda: router,
    )
    monkeypatch.setattr(
        lockfile,
        "installed_skill_names",
        lambda: {"planner"},
    )

    outcome = await search_skills(
        None,
        skill_search_request({"query": "plan", "limit": 3, "source": "github"}),
    )

    assert [result.name for result in outcome.results] == ["planner"]
    assert outcome.installed_names == {"planner"}
    assert outcome.unavailable is False
    assert calls == [("search", ("plan", 3, "github"))]


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
async def test_skill_publish_operation_delegates_to_publisher_boundary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from opensquilla.skills.hub import publisher

    calls: list[object] = []

    async def fake_publish_skill_from_request(request: object) -> SimpleNamespace:
        calls.append(request)
        return SimpleNamespace(success=True, message="ok", skill_name="demo")

    monkeypatch.setattr(
        publisher,
        "publish_skill_from_request",
        fake_publish_skill_from_request,
    )

    request = skill_publish_request(
        {"skill_dir": tmp_path / "demo-skill", "target_repo": "acme/skills"}
    )
    result = await publish_skill_from_request(request)

    assert result.success is True
    assert result.skill_name == "demo"
    assert calls == [request]


def test_tap_operations_delegate_to_taps_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.skills.hub import taps

    manager = object()
    calls: list[tuple[str, object]] = []

    def fake_taps_manager_factory() -> object:
        calls.append(("factory", None))
        return manager

    def fake_add_tap(actual_manager: object, request: object) -> SimpleNamespace:
        assert actual_manager is manager
        calls.append(("add", request))
        return SimpleNamespace(full_name="acme/tap", url="https://example.test/acme/tap")

    def fake_list_taps(actual_manager: object) -> list[SimpleNamespace]:
        assert actual_manager is manager
        calls.append(("list", None))
        return [SimpleNamespace(full_name="acme/tap")]

    def fake_remove_tap(actual_manager: object, request: object) -> bool:
        assert actual_manager is manager
        calls.append(("remove", request))
        return True

    monkeypatch.setattr(taps, "default_taps_manager_factory", fake_taps_manager_factory)
    monkeypatch.setattr(taps, "add_tap", fake_add_tap)
    monkeypatch.setattr(taps, "list_taps", fake_list_taps)
    monkeypatch.setattr(taps, "remove_tap", fake_remove_tap)

    actual_manager = default_taps_manager_factory()
    add_request = tap_add_request({"owner_repo": "acme/tap"})
    remove_request = tap_remove_request({"owner_repo": "acme/tap"})
    added = add_tap(actual_manager, add_request)
    listed = list_taps(actual_manager)
    removed = remove_tap(actual_manager, remove_request)

    assert actual_manager is manager
    assert added.full_name == "acme/tap"
    assert [tap.full_name for tap in listed] == ["acme/tap"]
    assert removed is True
    assert calls == [
        ("factory", None),
        ("add", add_request),
        ("list", None),
        ("remove", remove_request),
    ]


def test_default_skill_factories_delegate_to_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.skills.hub import defaults

    installer = object()
    router = object()

    monkeypatch.setattr(defaults, "get_default_skill_installer", lambda: installer)
    monkeypatch.setattr(defaults, "get_default_skill_router", lambda: router)

    assert default_skill_installer_factory() is installer
    assert default_skill_router_factory() is router


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
    local_installer = FakeInstaller()
    install_without_loader = await run_skill_install_operation(
        None,
        skill_install_request({"identifier": "planner"}),
        installer_factory=lambda: local_installer,
        require_loader=False,
    )

    assert missing_loader.unavailable_message == "No skill loader configured"
    assert missing_installer.unavailable_message == "No skill installer configured"
    assert install_outcome.result is not None
    assert install_without_loader.result is not None
    assert install_without_loader.result.success is True
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
