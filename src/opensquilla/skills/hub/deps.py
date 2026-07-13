"""Dependency installation for skills — brew, uv, download."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass

import structlog

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
        await proc.communicate()
        return -1, "", "Timed out"
    return (
        proc.returncode or 0,
        stdout.decode("utf-8", errors="replace"),
        stderr.decode("utf-8", errors="replace"),
    )


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
