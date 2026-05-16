"""Dependency installation for skills — brew, uv, download."""

from __future__ import annotations

import asyncio
import re
import weakref
from dataclasses import dataclass
from typing import Any, cast

import structlog

from opensquilla.skills.eligibility import EligibilityContext, diagnose_eligibility
from opensquilla.skills.types import SkillInstallSpec

log = structlog.get_logger(__name__)

# Strict allowlists to prevent arbitrary shell execution
_BREW_FORMULA_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9/_@.-]*$")
_UV_PACKAGE_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*(\[[a-zA-Z0-9,._-]+\])?$")
_URL_RE = re.compile(r"^https://[a-zA-Z0-9._/-]+$")


@dataclass
class DepResult:
    """Result of installing a single dependency."""

    kind: str
    identifier: str
    success: bool
    message: str = ""


@dataclass
class SkillDepsInstallOutcome:
    """Result of installing one dependency spec for a loaded skill."""

    result: DepResult
    missing_still: dict[str, list[str]]


@dataclass(frozen=True)
class SkillDepsInstallRequest:
    """Validated request to install one dependency spec for a loaded skill."""

    name: Any
    install_id: Any


_deps_locks: weakref.WeakValueDictionary[tuple[str, str], asyncio.Lock] = (
    weakref.WeakValueDictionary()
)


def _deps_lock_for(name: str, install_id: str) -> asyncio.Lock:
    key = (name, install_id)
    lock = _deps_locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _deps_locks[key] = lock
    return lock


async def _run(cmd: list[str], timeout: float = 120.0) -> tuple[int, str, str]:
    """Run a subprocess with timeout."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        return -1, "", "Timed out"
    return proc.returncode or 0, stdout.decode(), stderr.decode()


async def install_brew(spec: SkillInstallSpec) -> DepResult:
    """Install via Homebrew."""
    formula = spec.formula or spec.package or spec.id
    if not formula or not _BREW_FORMULA_RE.match(formula):
        return DepResult(
            kind="brew", identifier=formula, success=False, message=f"Invalid formula: {formula}"
        )

    code, out, err = await _run(["brew", "install", formula])
    if code == 0:
        return DepResult(kind="brew", identifier=formula, success=True, message="Installed")
    return DepResult(kind="brew", identifier=formula, success=False, message=err.strip()[:200])


async def install_uv(spec: SkillInstallSpec) -> DepResult:
    """Install a Python package via uv."""
    package = spec.package or spec.module or spec.id
    if not package or not _UV_PACKAGE_RE.match(package):
        return DepResult(
            kind="uv", identifier=package, success=False, message=f"Invalid package: {package}"
        )

    code, out, err = await _run(["uv", "pip", "install", package])
    if code == 0:
        return DepResult(kind="uv", identifier=package, success=True, message="Installed")
    return DepResult(kind="uv", identifier=package, success=False, message=err.strip()[:200])


async def install_download(spec: SkillInstallSpec) -> DepResult:
    """Download a binary from a URL."""
    import shutil
    from pathlib import Path

    url = spec.url
    if not url or not _URL_RE.match(url):
        return DepResult(
            kind="download", identifier=url or "", success=False, message=f"Invalid URL: {url}"
        )

    bin_name = spec.bins[0] if spec.bins else url.rsplit("/", 1)[-1]
    dest = Path.home() / ".local" / "bin" / bin_name

    code, out, err = await _run(["curl", "-fsSL", "-o", str(dest), url])
    if code != 0:
        return DepResult(kind="download", identifier=url, success=False, message=err.strip()[:200])

    dest.chmod(0o755)
    # Verify it landed on PATH
    if shutil.which(bin_name):
        return DepResult(
            kind="download", identifier=bin_name, success=True, message=f"Downloaded to {dest}"
        )
    return DepResult(
        kind="download",
        identifier=bin_name,
        success=True,
        message=f"Downloaded to {dest} (may need PATH update)",
    )


_INSTALLERS = {
    "brew": install_brew,
    "uv": install_uv,
    "download": install_download,
}


async def install_deps(specs: list[SkillInstallSpec]) -> list[DepResult]:
    """Install all dependencies for a skill. Returns results per spec."""
    results = []
    for spec in specs:
        handler = _INSTALLERS.get(spec.kind)
        if handler is None:
            results.append(
                DepResult(
                    kind=spec.kind,
                    identifier=spec.id,
                    success=False,
                    message=f"Unsupported install kind: {spec.kind}",
                )
            )
            continue
        try:
            result = await handler(spec)
        except FileNotFoundError:
            result = DepResult(
                kind=spec.kind,
                identifier=spec.id,
                success=False,
                message=f"Tool not found for kind '{spec.kind}' (brew/uv/curl)",
            )
        except Exception as exc:
            result = DepResult(
                kind=spec.kind,
                identifier=spec.id,
                success=False,
                message=f"Error: {exc}",
            )
        results.append(result)
        log.info("deps.install", kind=spec.kind, id=spec.id, success=result.success)
    return results


def skill_install_spec(skill: Any, install_id: str) -> SkillInstallSpec:
    """Return the install spec for a loaded skill."""

    metadata = getattr(skill, "metadata", None)
    specs = cast(
        "list[SkillInstallSpec]",
        metadata.install if metadata is not None else [],
    )
    spec = next((candidate for candidate in specs if candidate.id == install_id), None)
    if spec is None:
        raise KeyError(f"Install spec not found: {install_id}")
    return spec


def validate_skill_install_supported(spec: SkillInstallSpec, install_id: str) -> None:
    """Validate that an install spec is supported on the current OS."""

    ctx_eligible = EligibilityContext.auto()
    if spec.os and ctx_eligible.os_name and ctx_eligible.os_name not in spec.os:
        raise ValueError(
            f"Install spec {install_id!r} not supported on "
            f"{ctx_eligible.os_name} (requires: {', '.join(spec.os)})"
        )


def skill_missing_requirements(skill: Any) -> dict[str, list[str]]:
    """Return the current missing runtime requirements for a loaded skill."""

    report = diagnose_eligibility(skill, EligibilityContext.auto())
    return {
        "bins": list(report.missing_bins),
        "env": list(report.missing_env),
    }


def skill_deps_install_request(params: dict[str, Any] | None) -> SkillDepsInstallRequest:
    """Return a dependency install request from RPC params."""

    if not isinstance(params, dict):
        raise ValueError("params must be a dict")
    if "name" not in params:
        raise ValueError("params.name is required")
    if "install_id" not in params:
        raise ValueError("params.install_id is required")
    return SkillDepsInstallRequest(
        name=params["name"],
        install_id=params["install_id"],
    )


async def install_skill_dependency(
    skill: Any,
    *,
    name: str,
    install_id: str,
) -> SkillDepsInstallOutcome:
    """Install one dependency spec for a loaded skill and report remaining gaps."""

    spec = skill_install_spec(skill, install_id)
    validate_skill_install_supported(spec, install_id)

    async with _deps_lock_for(name, install_id):
        results = await install_deps([spec])
        return SkillDepsInstallOutcome(
            result=results[0],
            missing_still=skill_missing_requirements(skill),
        )


async def install_loaded_skill_dependency(
    loader: Any | None,
    request: SkillDepsInstallRequest,
) -> SkillDepsInstallOutcome:
    """Install one dependency spec by resolving the loaded skill from a loader."""

    if loader is None:
        raise KeyError("No skill loader available")
    skill = loader.get_by_name(request.name)
    if skill is None:
        raise KeyError(f"Skill not found: {request.name}")
    return await install_skill_dependency(
        skill,
        name=request.name,
        install_id=request.install_id,
    )
