"""Skills system for OpenSquilla.

Six-layer architecture (low→high precedence):
- Extra: config-specified additional directories
- Bundled: Ship with OpenSquilla in src/opensquilla/skills/bundled/
- Managed: Local installs in $OPENSQUILLA_STATE_DIR/skills/ (default ~/.opensquilla/skills/)
- Personal: Local user installs in ~/.agents/skills/
- Project: {workspace}/.agents/skills/
- Workspace: {workspace}/skills/

Only Bundled skills are shipped with OpenSquilla. Managed, Personal, Project,
Workspace, and Extra layers are local directories discovered at runtime.
"""

from __future__ import annotations

from opensquilla.skills.eligibility import (
    EligibilityContext,
    EligibilityReport,
    InstallHint,
    check_eligibility,
    diagnose_eligibility,
)
from opensquilla.skills.injector import SkillInjector
from opensquilla.skills.loader import SkillLoader
from opensquilla.skills.resources import SkillResources
from opensquilla.skills.runtime import (
    SkillLoaderSetup,
    configure_skill_loader,
    create_configured_skill_loader,
    current_skill_loader,
    reset_skill_runtime,
    skill_loader_available,
)
from opensquilla.skills.types import (
    SkillInstallSpec,
    SkillLayer,
    SkillPlatformMeta,
    SkillRequires,
    SkillSpec,
)

__all__ = [
    "EligibilityContext",
    "EligibilityReport",
    "InstallHint",
    "SkillInjector",
    "SkillInstallSpec",
    "SkillLayer",
    "SkillLoader",
    "SkillLoaderSetup",
    "SkillPlatformMeta",
    "SkillRequires",
    "SkillResources",
    "SkillSpec",
    "check_eligibility",
    "configure_skill_loader",
    "create_configured_skill_loader",
    "current_skill_loader",
    "diagnose_eligibility",
    "reset_skill_runtime",
    "skill_loader_available",
]
