"""Runtime failure classification for sandbox development recovery."""

from __future__ import annotations

import ipaddress
import os
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from urllib.parse import urlsplit

from opensquilla.sandbox.capability_profile import CapabilityProfile, NetworkIntent
from opensquilla.sandbox.dev_policy_matrix import NetworkTargetClass, PathTargetClass
from opensquilla.sandbox.sensitive_paths import sensitive_path_marker


class RecoveryFailureKind(StrEnum):
    DNS_FAILURE = "dns_failure"
    PROXY_DENIED = "proxy_denied"
    NETWORK_UNREACHABLE = "network_unreachable"


@dataclass(frozen=True)
class NetworkFailure:
    kind: RecoveryFailureKind
    host: str | None
    evidence: str


_DNS_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"Could not resolve host:\s*(?P<host>[^\s'\"<>]+)", re.IGNORECASE),
    re.compile(r"Could not resolve proxy:\s*(?P<host>[^\s'\"<>]+)", re.IGNORECASE),
    re.compile(r"Failed to resolve '(?P<host>[^']+)'", re.IGNORECASE),
    re.compile(r"Failed to resolve \"(?P<host>[^\"]+)\"", re.IGNORECASE),
    re.compile(r"Failed to resolve (?P<host>[^\s'\"<>]+)", re.IGNORECASE),
)
_DNS_MARKERS: tuple[str, ...] = (
    "temporary failure in name resolution",
    "name or service not known",
    "getaddrinfo failed",
    "nodename nor servname provided",
    "name resolution failed",
)
_PROXY_DENIED_MARKERS: tuple[str, ...] = (
    "407 proxy",
    "proxy authentication required",
    "proxy denied",
    "proxy authorization",
)
_NETWORK_UNREACHABLE_MARKERS: tuple[str, ...] = (
    "network is unreachable",
    "no route to host",
)
_LOCALHOST_NAMES = {"localhost", "localhost.localdomain"}
_URL_RE = re.compile(r"https?://[^\s'\"<>]+", re.IGNORECASE)
_TMP_ROOT = Path("/tmp")


def classify_network_failure(output: str) -> NetworkFailure | None:
    for line in output.splitlines() or [output]:
        for pattern in _DNS_PATTERNS:
            match = pattern.search(line)
            if match is not None:
                return NetworkFailure(
                    RecoveryFailureKind.DNS_FAILURE,
                    _clean_host(match.group("host")),
                    line,
                )

        lowered = line.lower()
        if any(marker in lowered for marker in _PROXY_DENIED_MARKERS):
            return NetworkFailure(RecoveryFailureKind.PROXY_DENIED, None, line)
        if any(marker in lowered for marker in _NETWORK_UNREACHABLE_MARKERS):
            return NetworkFailure(RecoveryFailureKind.NETWORK_UNREACHABLE, None, line)
        if any(marker in lowered for marker in _DNS_MARKERS):
            return NetworkFailure(RecoveryFailureKind.DNS_FAILURE, None, line)
    return None


def classify_path_target(
    path: Path,
    *,
    workspace: Path | None,
) -> PathTargetClass:
    try:
        candidate = path.expanduser().resolve(strict=False)
    except (OSError, RuntimeError):
        return PathTargetClass.UNCLEAR

    workspace_root: Path | None = None
    if workspace is not None:
        try:
            workspace_root = workspace.expanduser().resolve(strict=False)
        except (OSError, RuntimeError):
            workspace_root = None
    if workspace_root is not None and _is_relative_to(candidate, workspace_root):
        return PathTargetClass.WORKSPACE

    if sensitive_path_marker(str(candidate), workspace=workspace_root) is not None:
        return PathTargetClass.SENSITIVE

    if _is_relative_to(candidate, _TMP_ROOT):
        return PathTargetClass.TEMP

    if _is_user_owned_or_creatable(candidate):
        return PathTargetClass.NORMAL_USER_PATH

    return PathTargetClass.UNCLEAR


def network_class_for_failure(
    host: str | None,
    *,
    profile: CapabilityProfile,
    default: NetworkTargetClass,
    explicit_hosts: tuple[str, ...] = (),
) -> NetworkTargetClass:
    if host:
        host_class = _network_class_for_host(host)
        if host_class is not None:
            return host_class

    explicit_classes = tuple(
        target_class
        for explicit_host in explicit_hosts
        if (target_class := _network_class_for_host(explicit_host)) is not None
    )
    if NetworkTargetClass.METADATA_OR_LINK_LOCAL in explicit_classes:
        return NetworkTargetClass.METADATA_OR_LINK_LOCAL
    if NetworkTargetClass.PRIVATE_OR_LOCAL in explicit_classes:
        return NetworkTargetClass.PRIVATE_OR_LOCAL

    if profile.network_intent is NetworkIntent.PACKAGE_REGISTRY:
        return NetworkTargetClass.KNOWN_PACKAGE_REGISTRY
    if profile.network_intent in {
        NetworkIntent.SOURCE_FETCH,
        NetworkIntent.EXPLICIT_PUBLIC_URL,
    }:
        return NetworkTargetClass.SOURCE_FETCH
    if profile.network_intent is NetworkIntent.PRIVATE_OR_LOCAL:
        return NetworkTargetClass.PRIVATE_OR_LOCAL
    if profile.network_intent is NetworkIntent.METADATA_OR_LINK_LOCAL:
        return NetworkTargetClass.METADATA_OR_LINK_LOCAL
    if host:
        return NetworkTargetClass.UNKNOWN_PUBLIC
    return default


def explicit_network_hosts_from_command(command: str) -> tuple[str, ...]:
    hosts: list[str] = []
    for match in _URL_RE.finditer(command):
        parsed = urlsplit(match.group(0))
        if parsed.hostname:
            hosts.append(parsed.hostname)
    return tuple(hosts)


def _is_user_owned_or_creatable(path: Path) -> bool:
    uid = getattr(os, "getuid", lambda: None)()
    if uid is None:
        return False
    try:
        if path.exists():
            return path.stat().st_uid == uid
        for parent in path.parents:
            if parent.exists():
                return parent.stat().st_uid == uid and os.access(parent, os.W_OK | os.X_OK)
    except (OSError, RuntimeError):
        return False
    return False


def _is_relative_to(candidate: Path, root: Path) -> bool:
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def _network_class_for_host(host: str) -> NetworkTargetClass | None:
    normalized = _clean_host(host).lower()
    ip_class = _network_class_for_ip_literal(normalized)
    if ip_class is not None:
        return ip_class
    if normalized in _LOCALHOST_NAMES or normalized.endswith(".localhost"):
        return NetworkTargetClass.PRIVATE_OR_LOCAL
    return None


def _network_class_for_ip_literal(host: str) -> NetworkTargetClass | None:
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return None
    if address.is_link_local or str(address) == "169.254.169.254":
        return NetworkTargetClass.METADATA_OR_LINK_LOCAL
    if address.is_loopback or address.is_private:
        return NetworkTargetClass.PRIVATE_OR_LOCAL
    return NetworkTargetClass.UNKNOWN_PUBLIC


def _clean_host(host: str) -> str:
    cleaned = host.strip().strip(".,;:)'\"]")
    if cleaned.startswith("[") and "]" in cleaned:
        return cleaned[1 : cleaned.index("]")]
    if "://" in cleaned:
        cleaned = cleaned.split("://", 1)[1].split("/", 1)[0]
    if ":" in cleaned and cleaned.count(":") == 1:
        name, port = cleaned.rsplit(":", 1)
        if port.isdigit():
            return name
    return cleaned


__all__ = [
    "NetworkFailure",
    "RecoveryFailureKind",
    "classify_path_target",
    "classify_network_failure",
    "explicit_network_hosts_from_command",
    "network_class_for_failure",
]
