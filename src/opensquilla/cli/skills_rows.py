"""Local skill row loading for CLI skill views."""

from __future__ import annotations

from typing import Any


def load_skill_rows() -> list[dict[str, Any]]:
    """Load local skill rows for the CLI list view."""

    import os

    from opensquilla.gateway.config import GatewayConfig
    from opensquilla.skills.eligibility import EligibilityContext, check_eligibility
    from opensquilla.skills.runtime import create_configured_skill_loader

    config = GatewayConfig.load(os.environ.get("OPENSQUILLA_GATEWAY_CONFIG_PATH"))
    skill_setup = create_configured_skill_loader(
        config.skills,
        workspace_dir=config.workspace_dir,
    )
    loader = skill_setup.loader
    ctx = EligibilityContext.auto()
    rows: list[dict[str, Any]] = []
    for skill in sorted(loader.load_all(), key=lambda x: x.name):
        provenance = getattr(skill, "provenance", None)
        rows.append(
            {
                "name": skill.name,
                "layer": skill.layer.value,
                "eligible": check_eligibility(skill, ctx),
                "description": skill.description,
                "always": skill.always,
                "triggers": list(skill.triggers),
                "path": str(skill.path) if skill.path is not None else "",
                "filePath": skill.file_path,
                "baseDir": skill.base_dir,
                "homepage": skill.homepage,
                "userInvocable": skill.user_invocable,
                "disableModelInvocation": skill.disable_model_invocation,
                "provenance": {
                    "origin": provenance.origin if provenance else "unknown",
                    "license": provenance.license if provenance else "unknown",
                    "upstreamUrl": provenance.upstream_url if provenance else "",
                    "maintainedBy": provenance.maintained_by
                    if provenance
                    else "OpenSquilla",
                },
            }
        )
    return rows
