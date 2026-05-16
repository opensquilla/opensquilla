"""Process-wide skill runtime services."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from opensquilla.skills.loader import SkillLoader
    from opensquilla.skills.paths import SkillLayerDirs

_skill_loader: SkillLoader | None = None


@dataclass(frozen=True)
class SkillLoaderSetup:
    """Configured skill loader plus the resolved layer directories used to build it."""

    loader: SkillLoader
    layer_dirs: SkillLayerDirs


def create_configured_skill_loader(
    skills_config: Any,
    *,
    workspace_dir: str | Path | None = None,
) -> SkillLoaderSetup:
    """Create a skill loader from gateway/CLI skill configuration."""

    from opensquilla.skills.loader import SkillLoader
    from opensquilla.skills.paths import resolve_skill_layer_dirs

    workspace_root = Path(workspace_dir) if workspace_dir else None
    workspace_override_raw = getattr(skills_config, "workspace_dir", None)
    workspace_override = Path(workspace_override_raw) if workspace_override_raw else None
    layer_dirs = resolve_skill_layer_dirs(
        allow_bundled=getattr(skills_config, "allow_bundled", True),
        workspace_root=workspace_root,
        workspace_override=workspace_override,
        managed_override=getattr(skills_config, "managed_dir", None),
        extra_dirs=[Path(d) for d in getattr(skills_config, "extra_dirs", [])],
    )
    loader = SkillLoader(
        bundled_dir=layer_dirs.bundled_dir,
        workspace_dir=layer_dirs.workspace_dir,
        managed_dir=layer_dirs.managed_dir,
        personal_agents_dir=layer_dirs.personal_agents_dir,
        project_agents_dir=layer_dirs.project_agents_dir,
        extra_dirs=layer_dirs.extra_dirs,
    )
    return SkillLoaderSetup(loader=loader, layer_dirs=layer_dirs)


def configure_skill_loader(loader: SkillLoader | None) -> None:
    global _skill_loader
    _skill_loader = loader


def reset_skill_runtime() -> None:
    configure_skill_loader(None)


def current_skill_loader() -> SkillLoader | None:
    return _skill_loader


def skill_loader_available() -> bool:
    return _skill_loader is not None
