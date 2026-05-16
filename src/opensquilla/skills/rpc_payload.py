"""RPC payload builders for skills surfaces."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from opensquilla.skills.eligibility import (
    EligibilityContext,
    EligibilityReport,
    diagnose_eligibility,
)


def skill_status_from_report(report: EligibilityReport) -> str:
    """Map an eligibility report to the skills status wire enum."""

    if not report.eligible:
        return "needs_setup"
    if report.declared:
        return "ready"
    return "not_declared"


def skill_status_detail(spec: Any, report: EligibilityReport) -> str:
    """Build human-readable status detail for a skill row."""

    if not report.eligible:
        if report.disabled:
            return "Needs setup — disabled"
        if report.wrong_os:
            meta = getattr(spec, "metadata", None)
            os_list = list(meta.os) if meta and meta.os else []
            return f"Needs setup — wrong OS (requires: {', '.join(os_list)})"
        missing = list(report.missing_bins) + list(report.missing_env)
        if missing:
            return f"Needs setup — missing: {', '.join(missing)}"
        return "Needs setup"
    if not report.declared:
        return "Ready — no dependencies declared"
    meta = getattr(spec, "metadata", None)
    requires = meta.requires if meta is not None else None
    if requires is None:
        total = 0
    else:
        total = len(requires.bins) + (1 if requires.any_bins else 0) + len(requires.env)
    return f"Ready — {total}/{total} dependencies satisfied"


def skill_to_rpc_payload(
    spec: Any,
    report: EligibilityReport,
    os_name: str = "",
) -> dict[str, Any]:
    """Convert a SkillSpec to the installed skill RPC wire payload."""

    meta = getattr(spec, "metadata", None)
    install_entries: list[dict[str, Any]] = []
    if meta is not None:
        for ispec in meta.install:
            spec_os = list(getattr(ispec, "os", []) or [])
            if spec_os and os_name and os_name not in spec_os:
                continue
            install_entries.append(
                {
                    "id": ispec.id,
                    "kind": ispec.kind,
                    "label": ispec.label,
                    "bins": list(ispec.bins),
                }
            )

    payload: dict[str, Any] = {
        "name": spec.name,
        "description": spec.description,
        "layer": str(spec.layer),
        "always": spec.always,
        "triggers": spec.triggers,
        "eligible": report.eligible,
        "emoji": meta.emoji if meta else "",
        "primary_env": meta.primary_env if meta else "",
        "homepage": meta.homepage if meta else getattr(spec, "homepage", ""),
        "file_path": getattr(spec, "file_path", ""),
        "os": list(meta.os) if meta else [],
        "disabled": report.disabled,
        "install": install_entries,
    }
    provenance = getattr(spec, "provenance", None)
    payload["provenance"] = {
        "origin": provenance.origin if provenance else "unknown",
        "license": provenance.license if provenance else "unknown",
        "upstream_url": provenance.upstream_url if provenance else "",
        "maintained_by": provenance.maintained_by if provenance else "OpenSquilla",
    }
    payload["declared"] = report.declared
    payload["status"] = skill_status_from_report(report)
    payload["status_detail"] = skill_status_detail(spec, report)
    if not report.eligible:
        payload["reasons"] = report.reasons
        payload["missing_bins"] = report.missing_bins
        payload["missing_env"] = report.missing_env
    return payload


def skills_status_rpc_payload(loader: Any | None) -> list[dict[str, Any]]:
    """Build the RPC wire payload for ``skills.status``."""

    if loader is None:
        return []

    ctx_eligible = EligibilityContext.auto()
    skills = loader.load_all()
    return [
        skill_to_rpc_payload(skill, diagnose_eligibility(skill, ctx_eligible), ctx_eligible.os_name)
        for skill in skills
    ]


def skills_list_rpc_payload(loader: Any | None) -> dict[str, Any]:
    """Build the RPC wire payload for ``skills.list``."""

    if loader is None:
        return {"skills": []}
    return {"skills": skills_status_rpc_payload(loader)}


def skill_get_rpc_payload(params: Mapping[str, Any] | None, loader: Any | None) -> dict[str, Any]:
    """Build the RPC wire payload for ``skills.get``."""

    if not isinstance(params, Mapping) or "name" not in params:
        raise ValueError("params.name is required")
    if loader is None:
        raise KeyError("No skill loader available")

    name = params["name"]
    skill = loader.get_by_name(name)
    if skill is None:
        raise KeyError(f"Skill not found: {name}")

    ctx_eligible = EligibilityContext.auto()
    payload = skill_to_rpc_payload(
        skill,
        diagnose_eligibility(skill, ctx_eligible),
        ctx_eligible.os_name,
    )
    payload["content"] = skill.content
    payload["file_path"] = skill.file_path
    payload["base_dir"] = skill.base_dir
    return payload


def validate_skill_install_supported(spec: Any, install_id: str) -> None:
    """Validate that an install spec is supported on the current OS."""

    ctx_eligible = EligibilityContext.auto()
    if spec.os and ctx_eligible.os_name and ctx_eligible.os_name not in spec.os:
        raise ValueError(
            f"Install spec {install_id!r} not supported on "
            f"{ctx_eligible.os_name} (requires: {', '.join(spec.os)})"
        )


def skill_missing_requirements_rpc_payload(skill: Any) -> dict[str, list[str]]:
    """Build the post-install missing dependency payload for a skill."""

    report = diagnose_eligibility(skill, EligibilityContext.auto())
    return {
        "bins": list(report.missing_bins),
        "env": list(report.missing_env),
    }


__all__ = [
    "skill_get_rpc_payload",
    "skill_missing_requirements_rpc_payload",
    "skill_status_detail",
    "skill_status_from_report",
    "skill_to_rpc_payload",
    "skills_list_rpc_payload",
    "skills_status_rpc_payload",
    "validate_skill_install_supported",
]
