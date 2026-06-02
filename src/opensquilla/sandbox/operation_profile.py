"""Lightweight operation profiles for sandbox policy and prompts."""

from __future__ import annotations

import re
from dataclasses import dataclass

from opensquilla.sandbox.domain_validation import normalize_domain

_URL_RE = re.compile(r"https?://([^/\s]+)", re.IGNORECASE)


@dataclass(frozen=True)
class OperationProfile:
    name: str
    needs_network: bool = False
    package_manager: str | None = None
    requested_domains: tuple[str, ...] = ()
    requested_paths: tuple[str, ...] = ()
    high_impact: bool = False


def classify_command(argv: tuple[str, ...] | list[str]) -> OperationProfile:
    parts = tuple(str(p) for p in argv)
    lowered = tuple(p.lower() for p in parts)
    if _is_python_install(lowered):
        return OperationProfile("package_install", True, "python")
    if lowered and lowered[0] in {"npm", "pnpm", "yarn"} and "install" in lowered:
        return OperationProfile("package_install", True, "node")
    if lowered and lowered[0] == "cargo" and any(
        p in lowered for p in {"install", "build", "test"}
    ):
        return OperationProfile("package_install", True, "rust")
    if lowered and lowered[0] == "go" and any(
        p in lowered for p in {"get", "mod", "install"}
    ):
        return OperationProfile("package_install", True, "go")
    domains = _domains_from_argv(parts)
    if domains:
        return OperationProfile("network_fetch", True, requested_domains=domains)
    if _is_destructive(lowered):
        return OperationProfile("destructive_shell", high_impact=True)
    if lowered and lowered[0] in {"cat", "ls", "find", "rg"}:
        return OperationProfile("workspace_read")
    return OperationProfile("unknown_shell")


def package_bundle_for_manager(package_manager: str | None) -> str | None:
    return {
        "python": "python-package-install",
        "node": "node-package-install",
        "rust": "rust-package-install",
        "go": "go-package-install",
    }.get(package_manager or "")


def _is_python_install(lowered: tuple[str, ...]) -> bool:
    return (
        lowered[:3] == ("python", "-m", "pip")
        and "install" in lowered
    ) or (lowered and lowered[0] in {"pip", "pip3"} and "install" in lowered)


def _domains_from_argv(parts: tuple[str, ...]) -> tuple[str, ...]:
    domains: list[str] = []
    for part in parts:
        for match in _URL_RE.finditer(part):
            domain = normalize_domain(match.group(1))
            if domain and domain not in domains:
                domains.append(domain)
    return tuple(domains)


def _is_destructive(lowered: tuple[str, ...]) -> bool:
    if not lowered:
        return False
    if lowered[0] in {"rm", "del", "erase"}:
        return True
    return lowered[0] in {"mkfs", "format"}


__all__ = ["OperationProfile", "classify_command", "package_bundle_for_manager"]
