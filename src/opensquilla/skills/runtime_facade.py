"""Facade helpers for loaded skill runtime views."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from opensquilla.skills import eligibility as _eligibility
from opensquilla.skills.resources import SkillResources
from opensquilla.skills.types import SkillInstallSpec

EligibilityContext = _eligibility.EligibilityContext
EligibilityReport = _eligibility.EligibilityReport


def check_eligibility(skill: Any, ctx: EligibilityContext) -> bool:
    return _eligibility.check_eligibility(skill, ctx)


def diagnose_eligibility(skill: Any, ctx: EligibilityContext) -> EligibilityReport:
    return _eligibility.diagnose_eligibility(skill, ctx)

_BREW_FORMULA_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9/_@.+-]*$")
_NODE_PACKAGE_RE = re.compile(r"^(?:@[A-Za-z0-9][A-Za-z0-9._-]*/)?[A-Za-z0-9][A-Za-z0-9._-]*$")
_GO_MODULE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._~/-]*(?:@[A-Za-z0-9][A-Za-z0-9._~+-]*)?$")
_UV_PACKAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(\[[A-Za-z0-9,._-]+\])?$")


class SkillRuntimeFacadeError(ValueError):
    """Raised when a loaded skill runtime view cannot be built."""


@dataclass(frozen=True)
class SkillDependencyPreview:
    """Preview of a loaded skill dependency install command."""

    skill_name: str
    install_id: str
    spec: SkillInstallSpec
    argv: list[str]
    label: str

    @property
    def kind(self) -> str:
        return self.spec.kind

    def to_payload(self) -> dict[str, Any]:
        return {
            "status": "preview",
            "skill_name": self.skill_name,
            "install_id": self.install_id,
            "kind": self.spec.kind,
            "label": self.label,
            "argv": list(self.argv),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_payload())


def loaded_skill_rows(loader: Any) -> list[dict[str, Any]]:
    """Build CLI row dictionaries for skills loaded by *loader*."""

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


def skills_status_payload(loader: Any | None) -> list[dict[str, Any]]:
    """Build the RPC wire payload for ``skills.status``."""

    if loader is None:
        return []

    ctx_eligible = EligibilityContext.auto()
    skills = loader.load_all()
    return [
        skill_to_rpc_payload(skill, diagnose_eligibility(skill, ctx_eligible), ctx_eligible.os_name)
        for skill in skills
    ]


def skills_list_payload(loader: Any | None) -> dict[str, Any]:
    """Build the RPC wire payload for ``skills.list``."""

    if loader is None:
        return {"skills": []}
    return {"skills": skills_status_payload(loader)}


def skill_get_payload(params: Mapping[str, Any] | None, loader: Any | None) -> dict[str, Any]:
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


def loaded_skill_list_text(loader: Any | None) -> str:
    """Build the public ``skill_list`` tool text for loaded skills."""

    if loader is None:
        return "No skill loader available."
    skills = loader.load_all()
    if not skills:
        return "No skills installed."

    ctx = EligibilityContext.auto()
    lines = [f"Available skills ({len(skills)}):"]
    for skill in sorted(skills, key=lambda x: x.name):
        report = diagnose_eligibility(skill, ctx)
        lines.append(f"  - {skill.name}: {skill.description}")
        if not report.eligible:
            missing = []
            for binary in report.missing_bins:
                missing.append(f"{binary} (binary)")
            for env_name in report.missing_env:
                missing.append(f"{env_name} (env var)")
            if report.disabled:
                missing.append("disabled")
            if report.wrong_os:
                missing.append("wrong OS")
            if missing:
                lines.append(f"      [unavailable] Missing: {', '.join(missing)}")
            for hint in report.install_hints:
                lines.append(f"      Install: {hint.command}")
            for env_name in report.missing_env:
                lines.append(f"      Hint: Set environment variable {env_name}")
    return "\n".join(lines)


def read_loaded_skill_resource(
    loader: Any | None,
    name: str,
    file_path: str | None = None,
) -> str:
    """Read loaded skill body content or a supporting reference/script file."""

    if loader is None:
        return "No skill loader available."
    skill = loader.get_by_name(name)
    if skill is None:
        return f"Skill not found: {name}"

    if not file_path:
        return skill.content or f"(Skill '{name}' has no body content)"

    normalized_path = file_path.strip().lstrip("./")
    if normalized_path in {"", "SKILL.md"}:
        return skill.content or f"(Skill '{name}' has no body content)"

    resources = SkillResources(Path(skill.base_dir))
    content = _read_skill_resource(resources, normalized_path)
    if content is None:
        return f"File not found in skill '{name}': {file_path}"
    return content


def _read_skill_resource(resources: SkillResources, normalized_path: str) -> str | None:
    if normalized_path.startswith("references/"):
        return resources.read_reference(normalized_path.removeprefix("references/"))
    if normalized_path.startswith("scripts/"):
        return resources.read_script(normalized_path.removeprefix("scripts/"))
    return resources.read_reference(normalized_path) or resources.read_script(normalized_path)


def loaded_skill_dependency_preview(
    loader: Any | None,
    skill_name: str,
    install_id: str,
) -> SkillDependencyPreview:
    """Build a dependency install preview for a loaded skill install spec."""

    spec = _find_install_spec(loader, skill_name, install_id)
    argv = argv_for_install_spec(spec)
    label = spec.label or spec.id or "Install dependency"
    return SkillDependencyPreview(
        skill_name=skill_name,
        install_id=install_id,
        spec=spec,
        argv=argv,
        label=label,
    )


def argv_for_install_spec(spec: SkillInstallSpec) -> list[str]:
    """Build the safe argv for a supported skill dependency install spec."""

    kind = spec.kind
    if kind == "download":
        raise SkillRuntimeFacadeError("Install kind 'download' is deferred and cannot be executed")
    if kind == "brew":
        formula = _validate_install_value(
            spec.formula or spec.package,
            _BREW_FORMULA_RE,
            "formula",
        )
        return ["brew", "install", formula]
    if kind == "node":
        package = _validate_install_value(
            spec.package,
            _NODE_PACKAGE_RE,
            "package",
        )
        return ["npm", "install", "-g", "--ignore-scripts", package]
    if kind == "go":
        module = _validate_install_value(
            spec.module or spec.package,
            _GO_MODULE_RE,
            "module",
        )
        if "@" not in module:
            module = f"{module}@latest"
        return ["go", "install", module]
    if kind == "uv":
        package = _validate_install_value(
            spec.package or spec.module,
            _UV_PACKAGE_RE,
            "package",
        )
        return ["uv", "tool", "install", package]
    raise SkillRuntimeFacadeError(f"Unsupported install kind: {kind}")


def _find_install_spec(
    loader: Any | None,
    skill_name: str,
    install_id: str,
) -> SkillInstallSpec:
    if install_id.startswith("-"):
        raise SkillRuntimeFacadeError(f"Unsafe install value for install_id: {install_id}")
    if loader is None:
        raise SkillRuntimeFacadeError("Skill loader not available")

    skill = loader.get_by_name(skill_name)
    if skill is None:
        raise SkillRuntimeFacadeError(f"Skill not found: {skill_name}")
    if skill.metadata is None or not skill.metadata.install:
        raise SkillRuntimeFacadeError(f"Skill has no install metadata: {skill_name}")

    for index, spec in enumerate(skill.metadata.install):
        fallback_id = f"{spec.kind}-{index}"
        if spec.id == install_id or (not spec.id and install_id == fallback_id):
            return cast(SkillInstallSpec, spec)
    raise SkillRuntimeFacadeError(f"Install spec not found for skill '{skill_name}': {install_id}")


def _validate_install_value(value: str, pattern: re.Pattern[str], label: str) -> str:
    if not value:
        raise SkillRuntimeFacadeError(f"Missing install value: {label}")
    if value.startswith("-") or not pattern.match(value):
        raise SkillRuntimeFacadeError(f"Unsafe install value for {label}: {value}")
    return value


__all__ = [
    "SkillDependencyPreview",
    "SkillRuntimeFacadeError",
    "argv_for_install_spec",
    "loaded_skill_dependency_preview",
    "loaded_skill_list_text",
    "loaded_skill_rows",
    "read_loaded_skill_resource",
    "skill_get_payload",
    "skill_status_detail",
    "skill_status_from_report",
    "skill_to_rpc_payload",
    "skills_list_payload",
    "skills_status_payload",
]
