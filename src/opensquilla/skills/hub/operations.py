"""Operation helpers for Community skill management."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from opensquilla.skills.hub.installer import InstallResult, SkillInstaller

SkillInstallerFactory = Callable[[], SkillInstaller | None]


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


def invalidate_skill_loader(loader: Any | None) -> None:
    """Drop the skill loader's in-memory cache when one is configured."""

    if loader is not None:
        loader.invalidate_cache()


async def run_skill_install_operation(
    loader: Any | None,
    installer_factory: SkillInstallerFactory,
    request: SkillInstallRequest,
) -> SkillInstallOutcome:
    """Run ``skills.install`` with availability checks and cache invalidation."""

    if loader is None:
        return SkillInstallOutcome(unavailable_message="No skill loader configured")
    installer = installer_factory()
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
    installer_factory: SkillInstallerFactory,
    request: SkillUpdateRequest,
) -> SkillUpdateOutcome:
    """Run ``skills.update`` with availability checks and cache invalidation."""

    if loader is None:
        return SkillUpdateOutcome(
            results=[],
            unavailable_message="No skill loader configured",
        )
    installer = installer_factory()
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
    installer_factory: SkillInstallerFactory,
    request: SkillUninstallRequest,
) -> SkillUninstallOutcome:
    """Run ``skills.uninstall`` with availability checks and cache invalidation."""

    installer = installer_factory()
    if installer is None:
        return SkillUninstallOutcome(unavailable_message="No skill installer configured")

    result = await uninstall_skill(installer, request)
    if result.success:
        invalidate_skill_loader(loader)
    return SkillUninstallOutcome(result=result)
