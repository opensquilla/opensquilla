"""Skill tools — agent-accessible skill discovery, viewing, and management.

Registered at boot time when a SkillLoader is available.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from opensquilla.skills.types import SkillInstallSpec, SkillLayer
from opensquilla.tools.registry import tool
from opensquilla.tools.types import ToolError

if TYPE_CHECKING:
    from opensquilla.skills.loader import SkillLoader

logger = structlog.get_logger(__name__)

# Module-level reference set at boot
_loader: SkillLoader | None = None

# Layers that user may mutate — workspace only
_MUTABLE_LAYERS = frozenset({SkillLayer.WORKSPACE})

# Valid skill name pattern: lowercase alphanumeric + hyphens
_SKILL_NAME_RE = re.compile(r"^[a-z][a-z0-9\-]{0,62}$")
_INSTALL_OUTPUT_LIMIT = 4_000
_INSTALL_TIMEOUT_SECONDS = 120.0

_BREW_FORMULA_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9/_@.+-]*$")
_NODE_PACKAGE_RE = re.compile(r"^(?:@[A-Za-z0-9][A-Za-z0-9._-]*/)?[A-Za-z0-9][A-Za-z0-9._-]*$")
_GO_MODULE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._~/-]*(?:@[A-Za-z0-9][A-Za-z0-9._~+-]*)?$")
_UV_PACKAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(\[[A-Za-z0-9,._-]+\])?$")


def _sanitize_yaml_value(value: str) -> str:
    """Strip characters that could inject YAML structure."""
    return value.replace("\n", " ").replace("\r", " ").strip()


def _render_skill_md(
    name: str,
    description: str,
    content: str,
    triggers: list[str] | None = None,
) -> str:
    """Render a SKILL.md file from parts."""
    safe_desc = _sanitize_yaml_value(description)
    lines = ["---", f"name: {name}", f"description: {safe_desc}"]
    if triggers:
        lines.append("triggers:")
        for t in triggers:
            lines.append(f"  - {_sanitize_yaml_value(t)}")
    lines.append("---")
    lines.append("")
    lines.append(content)
    return "\n".join(lines)


def _cap_output(value: bytes | str, limit: int = _INSTALL_OUTPUT_LIMIT) -> str:
    if isinstance(value, bytes):
        text = value.decode(errors="replace")
    else:
        text = value
    if len(text) <= limit:
        return text
    omitted = len(text) - limit
    return f"{text[:limit]}\n... truncated {omitted} characters"


def _validate_install_value(value: str, pattern: re.Pattern[str], label: str) -> str:
    if not value:
        raise ToolError(f"Missing install value: {label}")
    if value.startswith("-") or not pattern.match(value):
        raise ToolError(f"Unsafe install value for {label}: {value}")
    return value


def _argv_for_install_spec(spec: SkillInstallSpec) -> list[str]:
    kind = spec.kind
    if kind == "download":
        raise ToolError("Install kind 'download' is deferred and cannot be executed")
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
    raise ToolError(f"Unsupported install kind: {kind}")


def _find_install_spec(skill_name: str, install_id: str) -> SkillInstallSpec:
    if install_id.startswith("-"):
        raise ToolError(f"Unsafe install value for install_id: {install_id}")
    if _loader is None:
        raise ToolError("Skill loader not available")

    skill = _loader.get_by_name(skill_name)
    if skill is None:
        raise ToolError(f"Skill not found: {skill_name}")
    if skill.metadata is None or not skill.metadata.install:
        raise ToolError(f"Skill has no install metadata: {skill_name}")

    for index, spec in enumerate(skill.metadata.install):
        fallback_id = f"{spec.kind}-{index}"
        if spec.id == install_id or (not spec.id and install_id == fallback_id):
            return spec
    raise ToolError(f"Install spec not found for skill '{skill_name}': {install_id}")


async def _run_install_argv(argv: list[str]) -> tuple[int, str, str, bool]:
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise ToolError(f"Install command not found: {argv[0]}") from exc
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(),
            timeout=_INSTALL_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        with contextlib.suppress(Exception):
            await proc.wait()
        return -1, "", "Timed out", True
    return proc.returncode or 0, _cap_output(stdout), _cap_output(stderr), False


def create_skill_tools(loader: SkillLoader) -> None:
    """Register skill tools (list, view, create, edit, delete) with the global registry."""
    global _loader
    _loader = loader

    @tool(
        name="skill_list",
        description="List all available skills with name, description, and eligibility.",
    )
    async def skill_list() -> str:
        if _loader is None:
            return "No skill loader available."
        skills = _loader.load_all()
        if not skills:
            return "No skills installed."

        from opensquilla.skills.eligibility import EligibilityContext, diagnose_eligibility

        ctx = EligibilityContext.auto()
        lines = [f"Available skills ({len(skills)}):"]
        for s in sorted(skills, key=lambda x: x.name):
            report = diagnose_eligibility(s, ctx)
            lines.append(f"  - {s.name}: {s.description}")
            if not report.eligible:
                missing = []
                for b in report.missing_bins:
                    missing.append(f"{b} (binary)")
                for e in report.missing_env:
                    missing.append(f"{e} (env var)")
                if report.disabled:
                    missing.append("disabled")
                if report.wrong_os:
                    missing.append("wrong OS")
                if missing:
                    lines.append(f"      [unavailable] Missing: {', '.join(missing)}")
                for hint in report.install_hints:
                    lines.append(f"      Install: {hint.command}")
                for e in report.missing_env:
                    lines.append(f"      Hint: Set environment variable {e}")
        return "\n".join(lines)

    @tool(
        name="skill_view",
        description=("Read a skill's SKILL.md content by name. Optionally read a supporting file."),
        params={
            "name": {
                "type": "string",
                "description": "Exact skill name to view",
            },
            "file_path": {
                "type": "string",
                "description": "Optional sub-file path (references/, scripts/)",
            },
        },
        required=["name"],
    )
    async def skill_view(name: str, file_path: str | None = None) -> str:
        if _loader is None:
            return "No skill loader available."
        skill = _loader.get_by_name(name)
        if skill is None:
            return (
                f"Skill not found: {name}. This skill is not available in the "
                "current skill catalog. Do not search host filesystem paths to "
                "recover missing skills. Use skill_list to inspect available "
                "skills, continue with available tools, or tell the user the "
                "skill is not installed."
            )

        if file_path:
            normalized_path = file_path.strip().lstrip("./")
            if normalized_path in {"", "SKILL.md"}:
                return skill.content or f"(Skill '{name}' has no body content)"

            from pathlib import Path

            from opensquilla.skills.resources import SkillResources

            resources = SkillResources(Path(skill.base_dir))
            content = resources.read_resource(normalized_path)
            if content is None:
                return f"File not found in skill '{name}': {file_path}"
            return content

        return skill.content or f"(Skill '{name}' has no body content)"

    @tool(
        name="install_skill_deps",
        description=(
            "Preview or install a skill dependency declared in skill metadata. "
            "Supports brew, node, go, and uv install specs."
        ),
        params={
            "skill_name": {
                "type": "string",
                "description": "Exact skill name containing the install metadata.",
            },
            "install_id": {
                "type": "string",
                "description": "Install spec id from the skill metadata install list.",
            },
            "confirmed": {
                "type": "boolean",
                "description": "When false, return preview JSON. When true, execute argv.",
                "default": False,
            },
        },
        required=["skill_name", "install_id"],
        owner_only=True,
    )
    async def install_skill_deps(
        skill_name: str,
        install_id: str,
        confirmed: bool = False,
    ) -> str:
        spec = _find_install_spec(skill_name, install_id)
        argv = _argv_for_install_spec(spec)
        label = spec.label or spec.id or "Install dependency"

        if not confirmed:
            return json.dumps(
                {
                    "status": "preview",
                    "skill_name": skill_name,
                    "install_id": install_id,
                    "kind": spec.kind,
                    "label": label,
                    "argv": argv,
                }
            )

        exit_code, stdout, stderr, timed_out = await _run_install_argv(argv)
        return json.dumps(
            {
                "status": "timeout" if timed_out else "executed",
                "skill_name": skill_name,
                "install_id": install_id,
                "kind": spec.kind,
                "label": label,
                "argv": argv,
                "exit_code": exit_code,
                "stdout": stdout,
                "stderr": stderr,
            }
        )

    # ── Mutation tools (workspace layer only) ──────────────────────────

    @tool(
        name="skill_create",
        description=(
            "Create a new skill in the workspace layer. "
            "Writes a SKILL.md file with frontmatter and body content."
        ),
        params={
            "name": {
                "type": "string",
                "description": "Skill name (lowercase, hyphens allowed, e.g. 'my-helper').",
            },
            "description": {
                "type": "string",
                "description": "One-line description of what the skill does.",
            },
            "content": {
                "type": "string",
                "description": "Skill body content (markdown).",
            },
            "triggers": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional trigger phrases for auto-activation.",
            },
        },
        required=["name", "description", "content"],
    )
    async def skill_create(
        name: str,
        description: str,
        content: str,
        triggers: list[str] | None = None,
    ) -> str:
        if _loader is None:
            raise ToolError("Skill loader not available")

        if not _SKILL_NAME_RE.match(name):
            raise ToolError(
                f"Invalid skill name: '{name}'. "
                "Use lowercase letters, digits, and hyphens (e.g. 'my-helper')."
            )

        if not description.strip():
            raise ToolError("Description must not be empty")

        if not content.strip():
            raise ToolError("Content must not be empty")

        # Check for name collision
        existing = _loader.get_by_name(name)
        if existing is not None:
            raise ToolError(
                f"Skill '{name}' already exists in layer '{existing.layer.value}'. "
                "Use skill_edit to modify it, or choose a different name."
            )

        # Write to workspace layer
        workspace_dir = _loader.workspace_dir
        if workspace_dir is None:
            raise ToolError("No workspace skill directory configured")

        skill_dir = workspace_dir / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_file = skill_dir / "SKILL.md"

        skill_md = _render_skill_md(name, description, content, triggers)
        skill_file.write_text(skill_md, encoding="utf-8")

        # Invalidate loader cache so new skill is discoverable
        _loader.invalidate_cache()

        logger.info("skill_create.success", name=name)
        return f"Skill '{name}' created at {skill_file}"

    @tool(
        name="skill_edit",
        description=(
            "Edit an existing skill's content or description. "
            "Only workspace-layer skills can be edited."
        ),
        params={
            "name": {
                "type": "string",
                "description": "Exact name of the skill to edit.",
            },
            "content": {
                "type": "string",
                "description": "New body content (replaces existing).",
            },
            "description": {
                "type": "string",
                "description": "New description (optional, keeps existing if omitted).",
            },
            "triggers": {
                "type": "array",
                "items": {"type": "string"},
                "description": "New trigger list (optional, keeps existing if omitted).",
            },
        },
        required=["name"],
    )
    async def skill_edit(
        name: str,
        content: str | None = None,
        description: str | None = None,
        triggers: list[str] | None = None,
    ) -> str:
        if _loader is None:
            raise ToolError("Skill loader not available")

        existing = _loader.get_by_name(name)
        if existing is None:
            raise ToolError(f"Skill not found: {name}")

        if existing.layer not in _MUTABLE_LAYERS:
            raise ToolError(
                f"Skill '{name}' is in layer '{existing.layer.value}' and cannot be edited. "
                "Only workspace-layer skills can be modified. "
                "Create a workspace override with skill_create instead."
            )

        if content is None and description is None and triggers is None:
            raise ToolError("Nothing to edit — provide content, description, or triggers")

        # Build updated SKILL.md
        new_description = description if description is not None else existing.description
        new_content = content if content is not None else (existing.content or "")
        new_triggers = triggers if triggers is not None else existing.triggers

        skill_file = Path(existing.file_path)
        if not skill_file.exists():
            raise ToolError(f"Skill file missing: {skill_file}")

        skill_md = _render_skill_md(name, new_description, new_content, new_triggers or None)
        skill_file.write_text(skill_md, encoding="utf-8")

        _loader.invalidate_cache()

        logger.info("skill_edit.success", name=name)
        return f"Skill '{name}' updated"

    @tool(
        name="skill_delete",
        description=(
            "Delete a skill from the workspace layer. Cannot delete bundled or managed skills."
        ),
        params={
            "name": {
                "type": "string",
                "description": "Exact name of the skill to delete.",
            },
        },
        required=["name"],
    )
    async def skill_delete(name: str) -> str:
        import shutil

        if _loader is None:
            raise ToolError("Skill loader not available")

        existing = _loader.get_by_name(name)
        if existing is None:
            raise ToolError(f"Skill not found: {name}")

        if existing.layer not in _MUTABLE_LAYERS:
            raise ToolError(
                f"Skill '{name}' is in layer '{existing.layer.value}' and cannot be deleted. "
                "Only workspace-layer skills can be removed."
            )

        skill_dir = Path(existing.base_dir)
        if not skill_dir.exists():
            raise ToolError(f"Skill directory missing: {skill_dir}")

        shutil.rmtree(skill_dir)
        _loader.invalidate_cache()

        logger.info("skill_delete.success", name=name)
        return f"Skill '{name}' deleted from workspace layer"

    logger.info("skill_tools.registered")
