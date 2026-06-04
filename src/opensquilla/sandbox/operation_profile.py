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
_URL_NETWORK_COMMANDS = frozenset({"aria2", "aria2c", "curl", "http", "httpie", "https", "wget"})
_GIT_NETWORK_COMMANDS = frozenset(
    {"clone", "fetch", "ls-remote", "pull", "push", "submodule"}
)
_READ_PATH_COMMANDS = frozenset(
    {"cat", "du", "find", "grep", "head", "ls", "rg", "tail", "tree"}
)
_COPY_PATH_COMMANDS = frozenset({"cp", "copy", "install", "rsync"})
_MOVE_PATH_COMMANDS = frozenset({"mv", "move", "ren", "rename"})
_ASSIGNMENT_RE = re.compile(r"[a-z_][a-z0-9_]*=.*")
_TRAILING_URL_PUNCTUATION = ".,;:!?)]}\"'`>"
_WINDOWS_ABSOLUTE_PATH_RE = re.compile(r"^[a-z]:[\\/]", re.IGNORECASE)
_WINDOWS_ABSOLUTE_PATH_IN_SCRIPT_RE = re.compile(
    r"(?<![a-z0-9_])[a-z]:[\\/]",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class OperationProfile:
    name: str
    needs_network: bool = False
    package_manager: str | None = None
    requested_domains: tuple[str, ...] = ()
    requested_paths: tuple[str, ...] = ()
    requested_write_paths: tuple[str, ...] = ()
    high_impact: bool = False


def classify_command(argv: tuple[str, ...] | list[str]) -> OperationProfile:
    parts = tuple(str(p) for p in argv)
    lowered = tuple(p.lower() for p in parts)
    if _is_python_install(lowered):
        return OperationProfile("package_install", True, "python")
    if _is_node_install(lowered):
        return OperationProfile("package_install", True, "node")
    if _is_rust_package_install(lowered):
        return OperationProfile("package_install", True, "rust")
    if _is_go_package_install(lowered):
        return OperationProfile("package_install", True, "go")
    if _is_shell_wrapper(lowered):
        script_profile = _classify_shell_script(parts)
        if _shell_script_is_destructive(lowered):
            return OperationProfile(
                "destructive_shell",
                needs_network=script_profile.needs_network,
                package_manager=script_profile.package_manager,
                requested_domains=script_profile.requested_domains,
                requested_paths=script_profile.requested_paths,
                requested_write_paths=script_profile.requested_write_paths,
                high_impact=True,
            )
        if (
            script_profile.needs_network
            or script_profile.requested_paths
            or script_profile.requested_write_paths
        ):
            return script_profile
        return OperationProfile("unknown_shell")
    if _is_destructive(lowered):
        return OperationProfile(
            "destructive_shell",
            requested_write_paths=_path_args_from_argv(parts),
            high_impact=True,
        )
    domains = _domains_from_argv(parts)
    if domains and _command_uses_http_url(lowered):
        return OperationProfile("url_fetch", True, requested_domains=domains)
    if lowered and _command_name(lowered[0]) in _READ_PATH_COMMANDS:
        return OperationProfile("workspace_read", requested_paths=_path_args_from_argv(parts))
    if lowered and _command_name(lowered[0]) in _COPY_PATH_COMMANDS:
        read_paths, write_paths = _copy_path_args_from_argv(parts)
        if read_paths or write_paths:
            return OperationProfile(
                "path_transfer",
                requested_paths=read_paths,
                requested_write_paths=write_paths,
            )
    if lowered and _command_name(lowered[0]) in _MOVE_PATH_COMMANDS:
        write_paths = _path_args_from_argv(parts)
        if write_paths:
            return OperationProfile("path_transfer", requested_write_paths=write_paths)
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
        len(lowered) >= 4
        and _PYTHON_EXE_RE.fullmatch(_command_name(lowered[0])) is not None
        and lowered[1:3] == ("-m", "pip")
        and lowered[3] == "install"
    ) or (
        len(lowered) >= 2
        and _command_name(lowered[0]) in {"pip", "pip3"}
        and lowered[1] == "install"
    )


def _is_node_install(lowered: tuple[str, ...]) -> bool:
    if not lowered or _command_name(lowered[0]) not in {"npm", "pnpm", "yarn"}:
        return False
    return len(lowered) >= 2 and lowered[1] in _NODE_INSTALL_COMMANDS


def _is_rust_package_install(lowered: tuple[str, ...]) -> bool:
    return (
        len(lowered) >= 2
        and _command_name(lowered[0]) == "cargo"
        and lowered[1] in {"build", "install", "test"}
    )


def _is_go_package_install(lowered: tuple[str, ...]) -> bool:
    if len(lowered) < 2 or _command_name(lowered[0]) != "go":
        return False
    if lowered[1] in {"get", "install"}:
        return True
    return len(lowered) >= 3 and lowered[1] == "mod" and lowered[2] in {
        "download",
        "tidy",
    }


def _command_uses_http_url(lowered: tuple[str, ...]) -> bool:
    if not lowered:
        return False
    command = _command_name(lowered[0])
    if command in _URL_NETWORK_COMMANDS:
        return True
    if command == "git" and len(lowered) >= 2:
        if lowered[1] in _GIT_NETWORK_COMMANDS:
            return True
        return len(lowered) >= 3 and lowered[1] == "submodule" and lowered[2] == "update"
    return False


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
        lexer = shlex.shlex(
            script,
            posix=_WINDOWS_ABSOLUTE_PATH_IN_SCRIPT_RE.search(script) is None,
            punctuation_chars=";&|",
        )
        lexer.whitespace_split = True
        return tuple(lexer)
    except ValueError:
        return tuple(script.split())


def _classify_shell_script(parts: tuple[str, ...]) -> OperationProfile:
    requested_paths: list[str] = []
    requested_write_paths: list[str] = []
    requested_domains: list[str] = []
    network_profile: OperationProfile | None = None
    for command_parts in _shell_commands(parts):
        profile = classify_command(command_parts)
        if profile.needs_network:
            if network_profile is None:
                network_profile = profile
            for domain in profile.requested_domains:
                if domain not in requested_domains:
                    requested_domains.append(domain)
        for path in profile.requested_paths:
            if path not in requested_paths:
                requested_paths.append(path)
        for path in profile.requested_write_paths:
            if path not in requested_write_paths:
                requested_write_paths.append(path)
    if network_profile is not None:
        return OperationProfile(
            network_profile.name,
            needs_network=True,
            package_manager=network_profile.package_manager,
            requested_domains=tuple(requested_domains),
            requested_paths=tuple(requested_paths),
            requested_write_paths=tuple(requested_write_paths),
            high_impact=network_profile.high_impact,
        )
    if requested_paths or requested_write_paths:
        return OperationProfile(
            "path_transfer" if requested_write_paths else "workspace_read",
            requested_paths=tuple(requested_paths),
            requested_write_paths=tuple(requested_write_paths),
        )
    return OperationProfile("unknown_shell")


def _shell_commands(parts: tuple[str, ...]) -> tuple[tuple[str, ...], ...]:
    commands: list[tuple[str, ...]] = []
    current: list[str] = []
    for token in _shell_tokens(_shell_script(parts)):
        if token in _SHELL_SEPARATORS:
            cleaned = _strip_assignment_prefix(tuple(current))
            if cleaned:
                commands.append(cleaned)
            current = []
            continue
        current.append(token)
    cleaned = _strip_assignment_prefix(tuple(current))
    if cleaned:
        commands.append(cleaned)
    return tuple(commands)


def _strip_assignment_prefix(parts: tuple[str, ...]) -> tuple[str, ...]:
    index = 0
    while index < len(parts) and _ASSIGNMENT_RE.fullmatch(parts[index].lower()):
        index += 1
    return parts[index:]


def _shell_script(parts: tuple[str, ...]) -> str:
    for index, part in enumerate(parts[1:], start=1):
        if _is_shell_command_option(part.lower()):
            return " ".join(parts[index + 1 :])
    return " ".join(parts[1:])


def _is_shell_command_option(part: str) -> bool:
    if part == "-c":
        return True
    if not part.startswith("-") or part.startswith("--"):
        return False
    return "c" in part[1:]


def _command_name(value: str) -> str:
    name = value.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    return name.removesuffix(".exe")


def _path_args_from_argv(parts: tuple[str, ...]) -> tuple[str, ...]:
    paths: list[str] = []
    for part in parts[1:]:
        cleaned = part.strip("'\"")
        if cleaned.startswith("-"):
            continue
        if not _looks_like_path_arg(cleaned):
            continue
        if cleaned not in paths:
            paths.append(cleaned)
    return tuple(paths)


def _copy_path_args_from_argv(parts: tuple[str, ...]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    path_args = _path_args_from_argv(parts)
    if len(path_args) < 2:
        return path_args, ()
    return path_args[:-1], path_args[-1:]


def _looks_like_path_arg(part: str) -> bool:
    if not part or part == "-":
        return False
    lowered = part.lower()
    if lowered.startswith(("http://", "https://")):
        return False
    return (
        part.startswith(("/", "~/", "~\\", "../", "..\\", "./", ".\\"))
        or _WINDOWS_ABSOLUTE_PATH_RE.match(part) is not None
    )


__all__ = ["OperationProfile", "classify_command", "package_bundle_for_manager"]
