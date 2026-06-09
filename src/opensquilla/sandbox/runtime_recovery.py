"""Runtime failure classification for sandbox development recovery."""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from enum import StrEnum

from opensquilla.sandbox.capability_profile import CapabilityProfile, NetworkIntent
from opensquilla.sandbox.dev_policy_matrix import NetworkTargetClass


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


def network_class_for_failure(
    host: str | None,
    *,
    profile: CapabilityProfile,
    default: NetworkTargetClass,
) -> NetworkTargetClass:
    if host:
        normalized = _clean_host(host).lower()
        ip_class = _network_class_for_ip_literal(normalized)
        if ip_class is not None:
            return ip_class
        if normalized in _LOCALHOST_NAMES or normalized.endswith(".localhost"):
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
    "classify_network_failure",
    "network_class_for_failure",
]
