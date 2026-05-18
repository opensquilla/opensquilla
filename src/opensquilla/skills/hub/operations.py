"""Operation helpers for Community skill management."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from opensquilla.skills.hub import search as _search

if TYPE_CHECKING:
    from opensquilla.skills.hub.deps import (
        SkillDepsInstallOutcome,
        SkillDepsInstallRequest,
    )
    from opensquilla.skills.hub.installer import InstallResult, SkillInstaller
    from opensquilla.skills.hub.publisher import PublishResult, SkillPublishRequest
    from opensquilla.skills.hub.taps import (
        Tap,
        TapAddRequest,
        TapRemoveRequest,
        TapsManager,
    )

SkillInstallerFactory = Callable[[], "SkillInstaller | None"]
SkillRouterFactory = _search.SkillRouterFactory
SkillSearchOutcome = _search.SkillSearchOutcome
SkillSearchRequest = _search.SkillSearchRequest
default_skill_router_factory = _search.default_skill_router_factory
installed_skill_names = _search.installed_skill_names
search_skills = _search.search_skills
skill_search_request = _search.skill_search_request


@dataclass(frozen=True)
class SkillInstallRequest:
    """Validated ``skills.install`` operation input."""

    identifier: Any
    source_id: Any
    force: Any


@dataclass(frozen=True)
class SkillUpdateRequest:
    """Validated ``skills.update`` operation input."""

    name: Any | None = None


@dataclass(frozen=True)
class SkillUninstallRequest:
    """Validated ``skills.uninstall`` operation input."""

    name: Any


@dataclass(frozen=True)
class SkillUpdateOutcome:
    """Result of updating managed Community skills."""

    results: list[InstallResult]
    unavailable_message: str = ""
    unavailable_payload: Literal["empty_results", "unavailable"] = "empty_results"


@dataclass(frozen=True)
class SkillInstallOutcome:
    """Result of running the ``skills.install`` operation workflow."""

    result: InstallResult | None = None
    unavailable_message: str = ""


@dataclass(frozen=True)
class SkillUninstallOutcome:
    """Result of running the ``skills.uninstall`` operation workflow."""

    result: InstallResult | None = None
    unavailable_message: str = ""


def skill_deps_install_request(
    params: Mapping[str, Any] | None,
) -> SkillDepsInstallRequest:
    """Build a ``skills.deps.install`` operation request from RPC params."""

    from opensquilla.skills.hub.deps import skill_deps_install_request as _build_request

    return _build_request(dict(params) if isinstance(params, Mapping) else params)


def skill_publish_request(params: Mapping[str, Any] | None) -> SkillPublishRequest:
    """Build a ``skills.publish`` operation request from CLI params."""

    from opensquilla.skills.hub.publisher import skill_publish_request as _build_request

    return _build_request(dict(params) if isinstance(params, Mapping) else params)


def tap_add_request(params: Mapping[str, Any] | None) -> TapAddRequest:
    """Build a ``skills.tap.add`` operation request from CLI params."""

    from opensquilla.skills.hub.taps import tap_add_request as _build_request

    return _build_request(dict(params) if isinstance(params, Mapping) else params)


def tap_remove_request(params: Mapping[str, Any] | None) -> TapRemoveRequest:
    """Build a ``skills.tap.remove`` operation request from CLI params."""

    from opensquilla.skills.hub.taps import tap_remove_request as _build_request

    return _build_request(dict(params) if isinstance(params, Mapping) else params)


def skill_install_request(params: Mapping[str, Any] | None) -> SkillInstallRequest:
    """Build a ``skills.install`` operation request from RPC params."""

    if not isinstance(params, Mapping) or "identifier" not in params:
        raise ValueError("params.identifier is required")

    return SkillInstallRequest(
        identifier=params["identifier"],
        source_id=params.get("source", "clawhub"),
        force=params.get("force", False),
    )


def skills_update_request(params: Mapping[str, Any] | None) -> SkillUpdateRequest:
    """Build a ``skills.update`` operation request from RPC params."""

    if params is None:
        return SkillUpdateRequest()
    return SkillUpdateRequest(name=params.get("name"))


def skill_uninstall_request(params: Mapping[str, Any] | None) -> SkillUninstallRequest:
    """Build a ``skills.uninstall`` operation request from RPC params."""

    if not isinstance(params, Mapping) or "name" not in params:
        raise ValueError("params.name is required")

    return SkillUninstallRequest(name=params["name"])


async def install_skill(
    installer: SkillInstaller,
    request: SkillInstallRequest,
) -> InstallResult:
    """Install a Community skill from a validated operation request."""

    return await installer.install(
        request.identifier,
        request.source_id,
        force=request.force,
    )


async def install_loaded_skill_dependency(
    loader: Any | None,
    request: SkillDepsInstallRequest,
) -> SkillDepsInstallOutcome:
    """Install a dependency spec by resolving a loaded skill from a loader."""

    from opensquilla.skills.hub.deps import (
        install_loaded_skill_dependency as _install_dependency,
    )

    return await _install_dependency(loader, request)


async def publish_skill_from_request(
    request: SkillPublishRequest,
) -> PublishResult:
    """Publish a skill from a validated operation request."""

    from opensquilla.skills.hub.publisher import publish_skill_from_request as _publish

    return await _publish(request)


def default_taps_manager_factory() -> TapsManager:
    """Return the default Community tap manager."""

    from opensquilla.skills.hub.taps import default_taps_manager_factory as _factory

    return _factory()


def add_tap(manager: TapsManager, request: TapAddRequest) -> Tap:
    """Register a Community skill tap from a validated operation request."""

    from opensquilla.skills.hub.taps import add_tap as _add_tap

    return _add_tap(manager, request)


def list_taps(manager: TapsManager) -> list[Tap]:
    """List registered Community skill taps."""

    from opensquilla.skills.hub.taps import list_taps as _list_taps

    return _list_taps(manager)


def remove_tap(manager: TapsManager, request: TapRemoveRequest) -> bool:
    """Remove a Community skill tap from a validated operation request."""

    from opensquilla.skills.hub.taps import remove_tap as _remove_tap

    return _remove_tap(manager, request)


def invalidate_skill_loader(loader: Any | None) -> None:
    """Drop the skill loader's in-memory cache when one is configured."""

    if loader is not None:
        loader.invalidate_cache()


def default_skill_installer_factory() -> SkillInstaller | None:
    """Return the default Community skill installer."""

    from opensquilla.skills.hub.defaults import get_default_skill_installer

    return get_default_skill_installer()


def _resolve_installer_factory(
    installer_factory: SkillInstallerFactory | None,
) -> SkillInstallerFactory:
    return default_skill_installer_factory if installer_factory is None else installer_factory


async def run_skill_install_operation(
    loader: Any | None,
    request: SkillInstallRequest,
    *,
    installer_factory: SkillInstallerFactory | None = None,
    require_loader: bool = True,
) -> SkillInstallOutcome:
    """Run ``skills.install`` with availability checks and cache invalidation."""

    if require_loader and loader is None:
        return SkillInstallOutcome(unavailable_message="No skill loader configured")
    installer = _resolve_installer_factory(installer_factory)()
    if installer is None:
        return SkillInstallOutcome(unavailable_message="No skill installer configured")

    result = await install_skill(installer, request)
    if result.success:
        invalidate_skill_loader(loader)
    return SkillInstallOutcome(result=result)


async def update_skills(
    installer: SkillInstaller,
    request: SkillUpdateRequest,
) -> SkillUpdateOutcome:
    """Update managed Community skills from a validated operation request."""

    try:
        return SkillUpdateOutcome(results=await installer.update(request.name))
    except OSError as exc:
        return SkillUpdateOutcome(
            results=[],
            unavailable_message=f"Skill update unavailable: {exc}",
        )


async def run_skills_update_operation(
    loader: Any | None,
    request: SkillUpdateRequest,
    *,
    installer_factory: SkillInstallerFactory | None = None,
) -> SkillUpdateOutcome:
    """Run ``skills.update`` with availability checks and cache invalidation."""

    if loader is None:
        return SkillUpdateOutcome(
            results=[],
            unavailable_message="No skill loader configured",
        )
    installer = _resolve_installer_factory(installer_factory)()
    if installer is None:
        return SkillUpdateOutcome(
            results=[],
            unavailable_message="No skill installer configured",
            unavailable_payload="unavailable",
        )

    outcome = await update_skills(installer, request)
    if any(result.success for result in outcome.results):
        invalidate_skill_loader(loader)
    return outcome


async def uninstall_skill(
    installer: SkillInstaller,
    request: SkillUninstallRequest,
) -> InstallResult:
    """Uninstall a managed Community skill from a validated operation request."""

    return await installer.uninstall(request.name)


async def run_skill_uninstall_operation(
    loader: Any | None,
    request: SkillUninstallRequest,
    *,
    installer_factory: SkillInstallerFactory | None = None,
) -> SkillUninstallOutcome:
    """Run ``skills.uninstall`` with availability checks and cache invalidation."""

    installer = _resolve_installer_factory(installer_factory)()
    if installer is None:
        return SkillUninstallOutcome(unavailable_message="No skill installer configured")

    result = await uninstall_skill(installer, request)
    if result.success:
        invalidate_skill_loader(loader)
    return SkillUninstallOutcome(result=result)
