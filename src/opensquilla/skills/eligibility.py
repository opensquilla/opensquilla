"""Eligibility filtering — checks if a skill is usable in the current environment."""

from __future__ import annotations

import os
import platform
import shutil
from dataclasses import dataclass, field

from opensquilla.skills.types import SkillInstallSpec, SkillSpec


@dataclass
class EligibilityContext:
    """Environment context for eligibility checks."""

    os_name: str = ""
    has_bin_cache: dict[str, bool] = field(default_factory=dict)
    env_cache: dict[str, str | None] = field(default_factory=dict)
    enabled_set: set[str] | None = None  # None = all enabled
    disabled_set: set[str] = field(default_factory=set)

    @staticmethod
    def auto(
        enabled_set: set[str] | None = None,
        disabled_set: set[str] | None = None,
    ) -> EligibilityContext:
        """Build context from the current environment."""
        return EligibilityContext(
            os_name=platform.system().lower(),
            enabled_set=enabled_set,
            disabled_set=disabled_set or set(),
        )


def _has_bin(name: str, ctx: EligibilityContext) -> bool:
    if name in ctx.has_bin_cache:
        return ctx.has_bin_cache[name]
    result = shutil.which(name) is not None
    ctx.has_bin_cache[name] = result
    return result


def _has_env(name: str, ctx: EligibilityContext) -> bool:
    if name in ctx.env_cache:
        return ctx.env_cache[name] is not None
    val = os.environ.get(name)
    ctx.env_cache[name] = val
    return val is not None


def check_eligibility(spec: SkillSpec, ctx: EligibilityContext) -> bool:
    """Check if a skill is eligible in the current environment.

    Returns False if any hard requirement is not met.
    """
    # 1. Explicitly disabled
    if spec.name in ctx.disabled_set:
        return False

    # 2. Explicitly enabled (whitelist mode)
    if ctx.enabled_set is not None and spec.name not in ctx.enabled_set:
        return False

    meta = spec.metadata
    if meta is None:
        return True  # No requirements → always eligible

    # 3. OS check
    if meta.os and ctx.os_name and ctx.os_name not in meta.os:
        return False

    # 4. Required bins (all must exist)
    if meta.requires:
        for b in meta.requires.bins:
            if not _has_bin(b, ctx):
                return False

        # 5. anyBins (at least one must exist)
        if meta.requires.any_bins:
            if not any(_has_bin(b, ctx) for b in meta.requires.any_bins):
                return False

        # 6. Required env vars
        for e in meta.requires.env:
            if not _has_env(e, ctx):
                return False

        # 7. envAny (at least one env var must exist)
        if meta.requires.env_any:
            if not any(_has_env(e, ctx) for e in meta.requires.env_any):
                return False

    return True


# ---------------------------------------------------------------------------
# Diagnostic report — detailed "why ineligible" + install hints
# ---------------------------------------------------------------------------


@dataclass
class InstallHint:
    """Display-only install command, decoupled from dependency execution logic."""

    kind: str  # "brew", "uv", "npm", "go", "download"
    label: str  # "Install himalaya (brew)"
    command: str  # "brew install himalaya"


@dataclass
class EligibilityReport:
    """Structured diagnosis of why a skill is or isn't eligible."""

    eligible: bool
    reasons: list[str] = field(default_factory=list)
    missing_bins: list[str] = field(default_factory=list)
    missing_env: list[str] = field(default_factory=list)
    missing_env_any: list[list[str]] = field(default_factory=list)
    install_hints: list[InstallHint] = field(default_factory=list)
    disabled: bool = False
    wrong_os: bool = False
    declared: bool = False


def _is_declared(spec: SkillSpec) -> bool:
    """Return True when the skill's frontmatter declares runtime requirements.

    Frontmatter with only ``metadata.emoji`` and no ``requires.*`` is not a
    declaration. ``requires.config`` is excluded — reserved/future,
    doesn't currently affect eligibility.
    """
    if spec.metadata is None:
        return False
    requires = spec.metadata.requires
    requires_declared = bool(
        requires
        and (
            requires.bins
            or requires.any_bins
            or requires.env
            or requires.env_any
        )
    )
    return requires_declared or bool(spec.metadata.install)


def _render_install_command(spec: SkillInstallSpec) -> str:
    """Render a display-only shell command from an install spec."""
    name = spec.formula or spec.package or spec.id
    if spec.kind == "brew":
        return f"brew install {name}" if name else ""
    if spec.kind == "uv":
        return f"uv pip install {spec.package}" if spec.package else ""
    if spec.kind == "npm":
        return f"npm install -g {spec.package}" if spec.package else ""
    if spec.kind == "go":
        return f"go install {spec.module}@latest" if spec.module else ""
    if spec.kind == "download" and spec.url:
        bin_name = spec.bins[0] if spec.bins else spec.id
        return (
            f"curl -fsSL -o ~/.local/bin/{bin_name} {spec.url} && chmod +x ~/.local/bin/{bin_name}"
        )
    return ""


def diagnose_eligibility(spec: SkillSpec, ctx: EligibilityContext) -> EligibilityReport:
    """Detailed diagnosis: calls check_eligibility for the gate, then collects reasons.

    The boolean in the report is always authoritative (from check_eligibility).
    The detail fields explain *why* the skill is ineligible.
    """
    eligible = check_eligibility(spec, ctx)
    if eligible:
        return EligibilityReport(eligible=True, declared=_is_declared(spec))

    reasons: list[str] = []
    missing_bins: list[str] = []
    missing_env: list[str] = []
    missing_env_any: list[list[str]] = []
    disabled = False
    wrong_os = False

    # Walk each check category to collect detail
    if spec.name in ctx.disabled_set:
        disabled = True
        reasons.append(f"Skill '{spec.name}' is disabled")

    if ctx.enabled_set is not None and spec.name not in ctx.enabled_set:
        disabled = True
        reasons.append(f"Skill '{spec.name}' not in enabled set")

    meta = spec.metadata
    if meta:
        if meta.os and ctx.os_name and ctx.os_name not in meta.os:
            wrong_os = True
            reasons.append(f"OS mismatch: requires {', '.join(meta.os)}, running {ctx.os_name}")

        if meta.requires:
            for b in meta.requires.bins:
                if not _has_bin(b, ctx):
                    missing_bins.append(b)
                    reasons.append(f"Missing binary: {b}")

            if meta.requires.any_bins:
                if not any(_has_bin(b, ctx) for b in meta.requires.any_bins):
                    for b in meta.requires.any_bins:
                        if not _has_bin(b, ctx):
                            missing_bins.append(b)
                    reasons.append(f"Need one of: {', '.join(meta.requires.any_bins)}")

            for e in meta.requires.env:
                if not _has_env(e, ctx):
                    missing_env.append(e)
                    reasons.append(f"Missing env var: {e}")

            if meta.requires.env_any:
                if not any(_has_env(e, ctx) for e in meta.requires.env_any):
                    missing_env_any.append(list(meta.requires.env_any))
                    reasons.append(
                        f"Need one env var from: {', '.join(meta.requires.env_any)}"
                    )

    # Match missing bins against install specs to produce hints
    install_hints: list[InstallHint] = []
    if meta and missing_bins:
        for ispec in meta.install:
            if ispec.bins and any(b in missing_bins for b in ispec.bins):
                cmd = _render_install_command(ispec)
                if cmd:
                    install_hints.append(
                        InstallHint(
                            kind=ispec.kind,
                            label=ispec.label or f"Install via {ispec.kind}",
                            command=cmd,
                        )
                    )

    return EligibilityReport(
        eligible=False,
        reasons=reasons,
        missing_bins=missing_bins,
        missing_env=missing_env,
        missing_env_any=missing_env_any,
        install_hints=install_hints,
        disabled=disabled,
        wrong_os=wrong_os,
        declared=_is_declared(spec),
    )
