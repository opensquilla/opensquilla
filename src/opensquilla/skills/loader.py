"""SKILL.md frontmatter parser and multi-layer skill loader."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, cast

import structlog
import yaml

from opensquilla.paths import default_opensquilla_home
from opensquilla.skills.meta.sop_compiler import (
    SOPCompileError,
)
from opensquilla.skills.meta.sop_compiler import (
    compile as _sop_compile,
)
from opensquilla.skills.types import (
    SkillInstallSpec,
    SkillLayer,
    SkillPlatformMeta,
    SkillProvenance,
    SkillRequires,
    SkillSpec,
)

log = structlog.get_logger(__name__)

MAX_SKILL_FILE_BYTES = 256_000  # 256KB per SKILL.md
MAX_SKILLS_PER_SOURCE = 200  # per layer cap

# Bump when on-disk snapshot fields change so stale caches are invalidated
# instead of silently losing new fields. v11 adds P1/P2 meta quality,
# preference, and policy metadata.
_SNAPSHOT_SCHEMA_VERSION = 11


def _string_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Parse YAML frontmatter from SKILL.md.

    Returns (frontmatter_dict, body_content).
    Handles both simple and nested metadata formats.
    """
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.DOTALL)
    if not match:
        return {}, text

    fm_text, body = match.groups()
    try:
        frontmatter = yaml.safe_load(fm_text)
    except yaml.YAMLError:
        return {}, text

    if not isinstance(frontmatter, dict):
        return {}, text

    return frontmatter, body.strip()


def _resolve_metadata(frontmatter: dict) -> SkillPlatformMeta | None:
    """Extract platform metadata from frontmatter."""
    raw_meta = frontmatter.get("metadata", {})
    if isinstance(raw_meta, dict):
        # Namespace fallback: platform > openclaw > clawdbot > top-level.
        # `opensquilla` overlays advisory fields such as risk/capabilities
        # without erasing platform dependency metadata kept at the top level
        # or in an upstream namespace.
        base_meta = raw_meta.get(
            "platform",
            raw_meta.get("openclaw", raw_meta.get("clawdbot", raw_meta)),
        )
        if not isinstance(base_meta, dict):
            base_meta = {}
        merged_meta = dict(base_meta)
        opensquilla_meta = raw_meta.get("opensquilla", {})
        if isinstance(opensquilla_meta, dict):
            for key in (
                "emoji",
                "skillKey",
                "primaryEnv",
                "homepage",
                "always",
                "os",
                "requires",
                "install",
                "risk",
                "risk_level",
                "riskLevel",
                "capabilities",
            ):
                if key in opensquilla_meta:
                    merged_meta[key] = opensquilla_meta[key]
        raw_meta = merged_meta
    if not isinstance(raw_meta, dict):
        return None

    requires = None
    raw_req = raw_meta.get("requires", {})
    if isinstance(raw_req, dict):
        # ClawHub frontmatter sometimes uses requires.commands instead of requires.bins.
        bins_value = raw_req.get("bins")
        if bins_value is None:
            bins_value = raw_req.get("commands", [])
        requires = SkillRequires(
            bins=bins_value if isinstance(bins_value, list) else [],
            any_bins=raw_req.get("anyBins", []),
            env=raw_req.get("env", []),
            env_any=raw_req.get("envAny", []),
            config=raw_req.get("config", []),
        )

    install_specs: list[SkillInstallSpec] = []
    for item in raw_meta.get("install", []):
        if isinstance(item, dict):
            install_specs.append(
                SkillInstallSpec(
                    kind=item.get("kind", ""),
                    id=item.get("id", ""),
                    label=item.get("label", ""),
                    bins=item.get("bins", []),
                    os=item.get("os", []),
                    formula=item.get("formula", ""),
                    package=item.get("package", ""),
                    module=item.get("module", ""),
                    url=item.get("url", ""),
                )
            )

    always_val = raw_meta.get("always")
    return SkillPlatformMeta(
        emoji=raw_meta.get("emoji", ""),
        skill_key=raw_meta.get("skillKey", ""),
        primary_env=raw_meta.get("primaryEnv", ""),
        homepage=raw_meta.get("homepage", ""),
        always=bool(always_val) if always_val is not None else None,
        os=_string_list(raw_meta.get("os", [])),
        requires=requires,
        install=install_specs,
        risk_level=str(
            raw_meta.get("risk")
            or raw_meta.get("risk_level")
            or raw_meta.get("riskLevel")
            or ""
        ).strip().lower(),
        capabilities=_string_list(raw_meta.get("capabilities", [])),
    )


def _resolve_provenance(frontmatter: dict) -> SkillProvenance:
    """Extract provenance metadata from top-level frontmatter."""
    raw = frontmatter.get("provenance", {})
    if not isinstance(raw, dict):
        raw = {}
    return SkillProvenance(
        origin=str(raw.get("origin") or "unknown"),
        license=str(raw.get("license") or "unknown"),
        upstream_url=str(raw.get("upstream_url") or ""),
        maintained_by=str(raw.get("maintained_by") or "OpenSquilla"),
    )


def _snapshot_provenance(raw: object) -> SkillProvenance:
    if not isinstance(raw, dict):
        return SkillProvenance()
    return SkillProvenance(
        origin=str(raw.get("origin") or "unknown"),
        license=str(raw.get("license") or "unknown"),
        upstream_url=str(raw.get("upstream_url") or ""),
        maintained_by=str(raw.get("maintained_by") or "OpenSquilla"),
    )


# Layer ordering: low precedence → high precedence
_LAYER_ORDER = [
    SkillLayer.EXTRA,
    SkillLayer.BUNDLED,
    SkillLayer.MANAGED,
    SkillLayer.PERSONAL,
    SkillLayer.PROJECT,
    SkillLayer.WORKSPACE,
]


class SkillLoader:
    """Loads and manages skills from multiple layered directories."""

    def __init__(
        self,
        bundled_dir: Path | None = None,
        workspace_dir: Path | None = None,
        managed_dir: Path | None = None,
        personal_agents_dir: Path | None = None,
        project_agents_dir: Path | None = None,
        extra_dirs: list[Path] | None = None,
        snapshot_path: Path | None = None,
    ) -> None:
        self._bundled_dir = bundled_dir
        self._workspace_dir = workspace_dir
        self._managed_dir = managed_dir
        self._personal_agents_dir = personal_agents_dir
        self._project_agents_dir = project_agents_dir
        self._extra_dirs = extra_dirs or []
        self._snapshot_path = (
            snapshot_path or default_opensquilla_home() / "cache" / "skills_snapshot.json"
        )
        self._cached: list[SkillSpec] | None = None

    @property
    def workspace_dir(self) -> Path | None:
        """Public accessor for workspace skill directory."""
        return self._workspace_dir

    @property
    def managed_dir(self) -> Path | None:
        """Public accessor for managed Community-installed skills."""
        return self._managed_dir

    def invalidate_cache(self) -> None:
        """Clear cached skills so next load_all() re-scans from disk."""
        self._cached = None

    def _get_layer_dirs(self) -> list[tuple[Path, SkillLayer]]:
        layer_dirs: list[tuple[Path, SkillLayer]] = []
        for d in self._extra_dirs:
            layer_dirs.append((d, SkillLayer.EXTRA))
        if self._bundled_dir:
            layer_dirs.append((self._bundled_dir, SkillLayer.BUNDLED))
        if self._managed_dir:
            layer_dirs.append((self._managed_dir, SkillLayer.MANAGED))
        if self._personal_agents_dir:
            layer_dirs.append((self._personal_agents_dir, SkillLayer.PERSONAL))
        if self._project_agents_dir:
            layer_dirs.append((self._project_agents_dir, SkillLayer.PROJECT))
        if self._workspace_dir:
            layer_dirs.append((self._workspace_dir, SkillLayer.WORKSPACE))
        return layer_dirs

    def _build_manifest(self) -> dict[str, dict[str, float | int]]:
        """Build a manifest of all SKILL.md files with mtime and size."""
        manifest: dict[str, dict[str, float | int]] = {}
        for dir_path, _layer in self._get_layer_dirs():
            if dir_path.exists():
                for skill_dir in sorted(dir_path.iterdir()):
                    if skill_dir.is_dir() and not skill_dir.name.startswith("."):
                        skill_file = skill_dir / "SKILL.md"
                        if skill_file.exists():
                            stat = skill_file.stat()
                            manifest[str(skill_file)] = {
                                "mtime": stat.st_mtime,
                                "size": stat.st_size,
                            }
        return manifest

    def save_snapshot(self) -> None:
        """Save loaded skills to disk cache for fast cold starts."""
        import json

        skills = self.load_all()
        manifest = self._build_manifest()
        data = {
            "version": _SNAPSHOT_SCHEMA_VERSION,
            "manifest": manifest,
            "skills": [
                {
                    "name": s.name,
                    "description": s.description,
                    "layer": s.layer.value,
                    "always": s.always,
                    "triggers": s.triggers,
                    "content": s.content,
                    "file_path": s.file_path,
                    "base_dir": s.base_dir,
                    "user_invocable": s.user_invocable,
                    "disable_model_invocation": s.disable_model_invocation,
                    "homepage": s.homepage,
                    "provenance": {
                        "origin": s.provenance.origin,
                        "license": s.provenance.license,
                        "upstream_url": s.provenance.upstream_url,
                        "maintained_by": s.provenance.maintained_by,
                    },
                    "metadata": {
                        "os": s.metadata.os if s.metadata else [],
                        "emoji": s.metadata.emoji if s.metadata else "",
                        "skill_key": s.metadata.skill_key if s.metadata else "",
                        "primary_env": s.metadata.primary_env if s.metadata else "",
                        "homepage": s.metadata.homepage if s.metadata else "",
                        "always": s.metadata.always if s.metadata else None,
                        "risk_level": s.metadata.risk_level if s.metadata else "",
                        "capabilities": s.metadata.capabilities if s.metadata else [],
                        "requires_bins": s.metadata.requires.bins
                        if s.metadata and s.metadata.requires
                        else [],
                        "requires_any_bins": s.metadata.requires.any_bins
                        if s.metadata and s.metadata.requires
                        else [],
                        "requires_env": s.metadata.requires.env
                        if s.metadata and s.metadata.requires
                        else [],
                        "requires_env_any": s.metadata.requires.env_any
                        if s.metadata and s.metadata.requires
                        else [],
                        "install": [
                            {
                                "kind": i.kind,
                                "id": i.id,
                                "label": i.label,
                                "bins": i.bins,
                                "os": i.os,
                                "formula": i.formula,
                                "package": i.package,
                                "module": i.module,
                                "url": i.url,
                            }
                            for i in (s.metadata.install if s.metadata else [])
                        ],
                    }
                    if s.metadata
                    else None,
                    "requires_tools": s.requires_tools,
                    "fallback_for_toolsets": s.fallback_for_toolsets,
                    "kind": s.kind,
                    "meta_priority": s.meta_priority,
                    "composition_raw": s.composition_raw,
                    "final_text_mode": s.final_text_mode,
                    "request_template": s.request_template,
                    "output_contract": s.output_contract,
                    "eval_prompts": s.eval_prompts,
                    "preference_keys": s.preference_keys,
                    "policy_tags": s.policy_tags,
                    "entrypoint": s.entrypoint,
                }
                for s in skills
            ],
        }
        self._snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        self._snapshot_path.write_text(json.dumps(data), encoding="utf-8")

    def load_snapshot(self) -> list[SkillSpec] | None:
        """Load from snapshot if manifest matches. Returns None on miss."""
        import json

        if not self._snapshot_path.exists():
            return None
        try:
            data = json.loads(self._snapshot_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

        if data.get("version") != _SNAPSHOT_SCHEMA_VERSION:
            return None
        saved_manifest = data.get("manifest", {})
        current_manifest = self._build_manifest()
        if saved_manifest != current_manifest:
            return None

        skills = []
        for s in data.get("skills", []):
            # Restore metadata from snapshot
            meta = None
            raw_meta = s.get("metadata")
            if raw_meta:
                from opensquilla.skills.types import (
                    SkillInstallSpec,
                    SkillPlatformMeta,
                    SkillRequires,
                )

                install_specs = [
                    SkillInstallSpec(
                        kind=i.get("kind", ""),
                        id=i.get("id", ""),
                        label=i.get("label", ""),
                        bins=i.get("bins", []),
                        os=i.get("os", []),
                        formula=i.get("formula", ""),
                        package=i.get("package", ""),
                        module=i.get("module", ""),
                        url=i.get("url", ""),
                    )
                    for i in raw_meta.get("install", [])
                ]
                meta = SkillPlatformMeta(
                    emoji=raw_meta.get("emoji", ""),
                    skill_key=raw_meta.get("skill_key", ""),
                    primary_env=raw_meta.get("primary_env", ""),
                    homepage=raw_meta.get("homepage", ""),
                    always=raw_meta.get("always"),
                    os=raw_meta.get("os", []),
                    requires=SkillRequires(
                        bins=raw_meta.get("requires_bins", []),
                        any_bins=raw_meta.get("requires_any_bins", []),
                        env=raw_meta.get("requires_env", []),
                        env_any=raw_meta.get("requires_env_any", []),
                    ),
                    install=install_specs,
                    risk_level=str(raw_meta.get("risk_level", "")).strip().lower(),
                    capabilities=raw_meta.get("capabilities", []),
                )

            skills.append(
                SkillSpec(
                    name=s["name"],
                    description=s.get("description", ""),
                    layer=SkillLayer(s.get("layer", "bundled")),
                    always=s.get("always", False),
                    triggers=s.get("triggers", []),
                    content=s.get("content", ""),
                    path=Path(s.get("base_dir", "")),
                    file_path=s.get("file_path", ""),
                    base_dir=s.get("base_dir", ""),
                    user_invocable=s.get("user_invocable", True),
                    disable_model_invocation=s.get("disable_model_invocation", False),
                    homepage=s.get("homepage", ""),
                    metadata=meta,
                    provenance=_snapshot_provenance(s.get("provenance")),
                    requires_tools=s.get("requires_tools", []),
                    fallback_for_toolsets=s.get("fallback_for_toolsets", []),
                    kind=s.get("kind", "skill"),
                    meta_priority=int(s.get("meta_priority", 0) or 0),
                    composition_raw=s.get("composition_raw"),
                    final_text_mode=str(s.get("final_text_mode", "auto") or "auto"),
                    request_template=(
                        dict(s.get("request_template") or {})
                        if isinstance(s.get("request_template"), dict)
                        else {}
                    ),
                    output_contract=(
                        dict(s.get("output_contract") or {})
                        if isinstance(s.get("output_contract"), dict)
                        else {}
                    ),
                    eval_prompts=(
                        [dict(item) for item in s.get("eval_prompts", []) if isinstance(item, dict)]
                        if isinstance(s.get("eval_prompts", []), list)
                        else []
                    ),
                    preference_keys=_string_list(s.get("preference_keys", [])),
                    policy_tags=_string_list(s.get("policy_tags", [])),
                    entrypoint=(
                        s["entrypoint"]
                        if isinstance(s.get("entrypoint"), dict)
                        else None
                    ),
                )
            )
        return skills

    def load_all(self) -> list[SkillSpec]:
        """Load all skills with layer precedence (high overrides low).

        Tries snapshot cache first for fast cold starts.
        """
        if self._cached is not None:
            return list(self._cached)

        # Try snapshot cache
        cached = self.load_snapshot()
        if cached is not None:
            self._cached = cached
            return list(cached)

        # Full scan: load in low→high order; higher layers override by name
        merged: dict[str, SkillSpec] = {}
        for dir_path, layer in self._get_layer_dirs():
            if dir_path.exists():
                layer_count = 0
                for skill_dir in sorted(dir_path.iterdir()):
                    if layer_count >= MAX_SKILLS_PER_SOURCE:
                        log.warning(
                            "layer %s has %d+ skills, truncating",
                            layer.value,
                            MAX_SKILLS_PER_SOURCE,
                        )
                        break
                    if skill_dir.is_dir() and not skill_dir.name.startswith("."):
                        spec = self._load_skill(skill_dir, layer, root=dir_path)
                        if spec:
                            prev = merged.get(spec.name)
                            if prev is not None and prev.kind != spec.kind:
                                # Higher layers override lower layers (per
                                # the loader contract). Log loud so the
                                # operator can spot accidental overrides
                                # — but do NOT raise: an unhandled
                                # RuntimeError here would break every
                                # subsequent turn via skills_filter's
                                # uncaught ``load_all()`` call.
                                log.warning(
                                    "skill.kind_override",
                                    name=spec.name,
                                    prev_kind=prev.kind,
                                    new_kind=spec.kind,
                                    prev_layer=prev.layer.value,
                                    new_layer=spec.layer.value,
                                    prev_path=str(getattr(prev, "base_dir", "")),
                                    new_path=str(getattr(spec, "base_dir", "")),
                                )
                            merged[spec.name] = spec
                            layer_count += 1

        # Pass 1 cache: populate so `get_by_name` works for SOP compilation
        # (compile needs to resolve referenced skills, which may not have
        # been encountered yet when the meta_sop was loaded — meta_sop
        # skills sort before their referenced regular skills in many cases).
        self._cached = list(merged.values())

        # Pass 2: compile any `kind: meta_sop` skills into normalised meta
        # skills. Failures are logged and the offending skill is dropped
        # from the loaded set (mirrors malformed regular skill handling).
        for sop_name in [n for n, s in merged.items() if s.kind == "meta_sop"]:
            sop_spec = merged[sop_name]
            try:
                merged[sop_name] = _sop_compile(sop_spec, skill_loader=self)
            except SOPCompileError as exc:
                log.warning(
                    "sop_compile_failed",
                    skill=sop_name,
                    error=str(exc),
                )
                del merged[sop_name]

        skills = list(merged.values())
        self._cached = list(skills)

        # Save snapshot for next cold start
        try:
            self.save_snapshot()
        except OSError:
            pass

        return skills

    def _load_skill(
        self, skill_dir: Path, layer: SkillLayer, root: Path | None = None
    ) -> SkillSpec | None:
        """Load a single skill from its directory."""
        # Symlink containment: reject skills that escape the layer root
        if root is not None:
            try:
                real = skill_dir.resolve()
                if not real.is_relative_to(root.resolve()):
                    log.warning("skill %s escapes root %s, skipping", skill_dir.name, root)
                    return None
            except (OSError, ValueError):
                return None

        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            return None

        # File size guard
        try:
            if skill_file.stat().st_size > MAX_SKILL_FILE_BYTES:
                log.warning(
                    "skill %s exceeds %d bytes, skipping",
                    skill_dir.name,
                    MAX_SKILL_FILE_BYTES,
                )
                return None
        except OSError:
            return None

        try:
            text = skill_file.read_text(encoding="utf-8")
            frontmatter, body = _parse_frontmatter(text)

            if not frontmatter or "name" not in frontmatter:
                return None

            name = frontmatter["name"]
            description = frontmatter.get("description", "")

            # Simple fields
            always_raw = frontmatter.get("always", False)
            always = bool(always_raw) if always_raw is not None else False

            triggers = frontmatter.get("triggers", [])
            if not isinstance(triggers, list):
                triggers = [str(triggers)]

            # Platform metadata fields
            metadata = _resolve_metadata(frontmatter)
            provenance = _resolve_provenance(frontmatter)
            # metadata.always overrides top-level always if set
            if metadata and metadata.always is not None:
                always = metadata.always

            user_invocable = frontmatter.get("user-invocable", True)
            disable_model_invocation = frontmatter.get(
                "disable-model-invocation",
                False,
            )
            homepage = frontmatter.get("homepage", "")

            # Conditional activation fields
            activation_meta: dict[str, Any] = {}
            raw_meta_dict = frontmatter.get("metadata", {})
            if isinstance(raw_meta_dict, dict):
                raw_activation_meta = raw_meta_dict.get("opensquilla", {})
                if isinstance(raw_activation_meta, dict):
                    activation_meta = cast(dict[str, Any], raw_activation_meta)
            requires_tools = activation_meta.get("requires_tools", [])
            fallback_for_toolsets = activation_meta.get("fallback_for_toolsets", [])

            # Meta-Skill fields (MVP): kind, meta_priority, composition_raw.
            # Non-meta skills get the defaults; behavior unchanged.
            kind_raw = frontmatter.get("kind", "skill")
            kind = str(kind_raw) if isinstance(kind_raw, str) else "skill"
            meta_priority_raw = frontmatter.get("meta_priority", 0)
            try:
                meta_priority = int(meta_priority_raw) if meta_priority_raw is not None else 0
            except (TypeError, ValueError):
                meta_priority = 0
            composition_raw = frontmatter.get("composition")
            if not isinstance(composition_raw, dict):
                composition_raw = None

            entrypoint_raw = frontmatter.get("entrypoint")
            entrypoint = entrypoint_raw if isinstance(entrypoint_raw, dict) else None

            # final_text_mode is a meta-skill-only optional field; non-meta
            # skills keep the default "auto" but never consume it.
            final_text_mode_raw = frontmatter.get("final_text_mode", "auto")
            final_text_mode = (
                str(final_text_mode_raw).strip() if final_text_mode_raw else "auto"
            ) or "auto"
            request_template_raw = frontmatter.get("request_template")
            request_template = (
                dict(request_template_raw)
                if isinstance(request_template_raw, dict)
                else {}
            )
            output_contract_raw = frontmatter.get("output_contract")
            output_contract = (
                dict(output_contract_raw)
                if isinstance(output_contract_raw, dict)
                else {}
            )
            eval_prompts_raw = frontmatter.get("eval_prompts")
            eval_prompts = (
                [dict(item) for item in eval_prompts_raw if isinstance(item, dict)]
                if isinstance(eval_prompts_raw, list)
                else []
            )
            preference_keys = _string_list(frontmatter.get("preference_keys", []))
            policy_tags = _string_list(frontmatter.get("policy_tags", []))

            return SkillSpec(
                name=name,
                description=description,
                layer=layer,
                always=always,
                triggers=triggers,
                content=body,
                path=skill_dir,
                metadata=metadata,
                provenance=provenance,
                user_invocable=user_invocable,
                disable_model_invocation=disable_model_invocation,
                homepage=homepage,
                file_path=str(skill_file.resolve()),
                base_dir=str(skill_dir.resolve()),
                requires_tools=requires_tools if isinstance(requires_tools, list) else [],
                fallback_for_toolsets=fallback_for_toolsets
                if isinstance(fallback_for_toolsets, list)
                else [],
                kind=kind,
                meta_priority=meta_priority,
                composition_raw=composition_raw,
                final_text_mode=final_text_mode,
                request_template=request_template,
                output_contract=output_contract,
                eval_prompts=eval_prompts,
                preference_keys=preference_keys,
                policy_tags=policy_tags,
                entrypoint=entrypoint,
            )
        except Exception as exc:
            log.debug("skill.load_failed", dir=str(skill_dir), error=str(exc))
            return None

    def filter_by_tools(self, available_tools: set[str]) -> list[SkillSpec]:
        """Return skills whose requires_tools are all present in available_tools.

        Skills with no requires_tools pass unconditionally.
        """
        result = []
        for s in self.load_all():
            if s.requires_tools and not all(t in available_tools for t in s.requires_tools):
                continue
            result.append(s)
        return result

    def find_by_trigger(self, text: str) -> list[SkillSpec]:
        """Find skills matching triggers in the given text."""
        text_lower = text.lower()
        matches: list[SkillSpec] = []
        for skill in self.load_all():
            for trigger in skill.triggers:
                if trigger.lower() in text_lower:
                    matches.append(skill)
                    break
        return matches

    def get_always_skills(self) -> list[SkillSpec]:
        """Get all skills with always=True."""
        return [skill for skill in self.load_all() if skill.always]

    def get_user_invocable(self) -> list[SkillSpec]:
        """Get all skills that are user-invocable."""
        return [skill for skill in self.load_all() if skill.user_invocable]

    def get_by_name(self, name: str) -> SkillSpec | None:
        """Get a skill by exact name."""
        for skill in self.load_all():
            if skill.name == name:
                return skill
        return None

    def list_meta_specs(self) -> list[SkillSpec]:
        """Return all loaded specs with kind == 'meta'.

        Note: loader Pass 2 compiles authored 'meta_sop' specs into
        'meta' shape before they reach this function, so meta_sop authors
        ARE included. The helper exists to centralize that contract — do
        not filter against 'meta_sop' here.
        """
        return [spec for spec in self.load_all() if spec.kind == "meta"]
