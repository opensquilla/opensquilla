"""Lightweight operation profiles for sandbox policy and prompts."""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass

from opensquilla.sandbox.domain_validation import normalize_domain

_PYTHON_EXE_RE = re.compile(r"python(?:\d+(?:\.\d+)*)?$")
_URL_RE = re.compile(r"https?://[^\s]+", re.IGNORECASE)
_NODE_INSTALL_COMMANDS = frozenset({"add", "ci", "install"})
_SHELL_WRAPPERS = frozenset({"bash", "dash", "fish", "ksh", "sh", "zsh"})
_DESTRUCTIVE_COMMANDS = frozenset({"del", "erase", "format", "mkfs", "rm"})
_SHELL_SEPARATORS = frozenset({"&&", "||", ";", "|"})
_ASSIGNMENT_RE = re.compile(r"[a-z_][a-z0-9_]*=.*")
_TRAILING_URL_PUNCTUATION = ".,;:!?)]}\"'`>"


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
    if _is_node_install(lowered):
        return OperationProfile("package_install", True, "node")
    if lowered and _command_name(lowered[0]) == "cargo" and any(
        p in lowered for p in {"install", "build", "test"}
    ):
        return OperationProfile("package_install", True, "rust")
    if lowered and _command_name(lowered[0]) == "go" and any(
        p in lowered for p in {"get", "mod", "install"}
    ):
        return OperationProfile("package_install", True, "go")
    if _is_shell_wrapper(lowered):
        if _shell_script_is_destructive(lowered):
            return OperationProfile("destructive_shell", high_impact=True)
        return OperationProfile("unknown_shell")
    domains = _domains_from_argv(parts)
    if domains:
        return OperationProfile("url_fetch", True, requested_domains=domains)
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
        len(lowered) >= 3
        and _PYTHON_EXE_RE.fullmatch(_command_name(lowered[0])) is not None
        and lowered[1:3] == ("-m", "pip")
        and "install" in lowered
    ) or (
        lowered
        and _command_name(lowered[0]) in {"pip", "pip3"}
        and "install" in lowered
    )


def _is_node_install(lowered: tuple[str, ...]) -> bool:
    if not lowered or _command_name(lowered[0]) not in {"npm", "pnpm", "yarn"}:
        return False
    return any(part in _NODE_INSTALL_COMMANDS for part in lowered[1:])


def _domains_from_argv(parts: tuple[str, ...]) -> tuple[str, ...]:
    domains: list[str] = []
    for part in parts:
        for match in _URL_RE.finditer(part):
            domain = normalize_domain(match.group(0).rstrip(_TRAILING_URL_PUNCTUATION))
            if domain and domain not in domains:
                domains.append(domain)
    return tuple(domains)


def _is_destructive(lowered: tuple[str, ...]) -> bool:
    if not lowered:
        return False
    return _command_name(lowered[0]) in _DESTRUCTIVE_COMMANDS


def _is_shell_wrapper(lowered: tuple[str, ...]) -> bool:
    return bool(lowered) and _command_name(lowered[0]) in _SHELL_WRAPPERS


def _shell_script_is_destructive(lowered: tuple[str, ...]) -> bool:
    command_expected = True
    for token in _shell_tokens(_shell_script(lowered)):
        if token in _SHELL_SEPARATORS:
            command_expected = True
            continue
        if command_expected:
            lowered_token = token.lower()
            if _ASSIGNMENT_RE.fullmatch(lowered_token):
                continue
            if _command_name(lowered_token) in _DESTRUCTIVE_COMMANDS:
                return True
            command_expected = False
    return False


def _shell_tokens(script: str) -> tuple[str, ...]:
    try:
        lexer = shlex.shlex(script, posix=True, punctuation_chars=";&|")
        lexer.whitespace_split = True
        return tuple(lexer)
    except ValueError:
        return tuple(script.split())


def _shell_script(lowered: tuple[str, ...]) -> str:
    for index, part in enumerate(lowered[1:], start=1):
        if part.startswith("-") and "c" in part:
            return " ".join(lowered[index + 1 :])
    return " ".join(lowered[1:])


def _command_name(value: str) -> str:
    name = value.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    return name.removesuffix(".exe")


__all__ = ["OperationProfile", "classify_command", "package_bundle_for_manager"]
