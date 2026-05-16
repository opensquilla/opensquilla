"""Default Community skill hub dependencies."""

from __future__ import annotations

import os
from collections.abc import Mapping

from opensquilla.skills.hub.clawhub import ClawHubSource
from opensquilla.skills.hub.github import GitHubSource
from opensquilla.skills.hub.installer import SkillInstaller
from opensquilla.skills.hub.router import SourceRouter
from opensquilla.skills.hub.source import SkillSource

_default_router: SourceRouter | None = None
_default_installer: SkillInstaller | None = None


def build_default_skill_sources(env: Mapping[str, str] | None = None) -> list[SkillSource]:
    """Build the default Community skill sources."""

    token_env = os.environ if env is None else env
    return [
        ClawHubSource(token=token_env.get("CLAWHUB_TOKEN")),
        GitHubSource(token=token_env.get("GITHUB_TOKEN")),
    ]


def build_default_skill_router(env: Mapping[str, str] | None = None) -> SourceRouter:
    """Build a fresh default Community skill source router."""

    return SourceRouter(build_default_skill_sources(env))


def build_default_skill_installer(env: Mapping[str, str] | None = None) -> SkillInstaller:
    """Build a fresh default Community skill installer."""

    return SkillInstaller(router=build_default_skill_router(env))


def get_default_skill_router() -> SourceRouter:
    """Return the cached default Community skill source router."""

    global _default_router
    if _default_router is None:
        _default_router = build_default_skill_router()
    return _default_router


def get_default_skill_installer() -> SkillInstaller:
    """Return the cached default Community skill installer."""

    global _default_installer
    if _default_installer is None:
        _default_installer = SkillInstaller(router=get_default_skill_router())
    return _default_installer


def reset_default_skill_hub() -> None:
    """Reset cached default Community skill hub dependencies."""

    global _default_router, _default_installer
    _default_router = None
    _default_installer = None


__all__ = [
    "build_default_skill_installer",
    "build_default_skill_router",
    "build_default_skill_sources",
    "get_default_skill_installer",
    "get_default_skill_router",
    "reset_default_skill_hub",
]
