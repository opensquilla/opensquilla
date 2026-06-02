"""Domain normalization and safety checks for sandbox managed network."""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlparse

DomainStatus = Literal["allowed", "blocked"]


@dataclass(frozen=True)
class DomainDecision:
    status: DomainStatus
    normalized: str
    reason: str


_METADATA_IPS = {
    ipaddress.ip_address("169.254.169.254"),
    ipaddress.ip_address("100.100.100.200"),
}


def normalize_domain(raw: str) -> str:
    text = str(raw or "").strip().lower()
    if not text:
        return ""
    if "://" in text:
        parsed = urlparse(text)
        text = parsed.hostname or ""
    else:
        text = text.split("/", 1)[0]
        text = text.split(":", 1)[0] if not text.startswith("[") else text
    return text.strip(".").lower()


def validate_domain_pattern(raw: str) -> DomainDecision:
    normalized = normalize_domain(raw)
    if not normalized:
        return DomainDecision("blocked", normalized, "empty_domain")
    if _is_ip_literal(normalized):
        return DomainDecision("blocked", normalized, "ip_literal")
    if normalized.startswith("*."):
        suffix = normalized[2:]
        if suffix.count(".") < 1:
            return DomainDecision("blocked", normalized, "broad_wildcard")
        tld = suffix.rsplit(".", 1)[-1]
        if suffix == tld or normalized in {"*.com", "*.org", "*.net", "*.io", "*.dev"}:
            return DomainDecision("blocked", normalized, "broad_wildcard")
        return DomainDecision("allowed", normalized, "wildcard_domain")
    if "*" in normalized:
        return DomainDecision("blocked", normalized, "invalid_wildcard")
    if "." not in normalized:
        return DomainDecision("blocked", normalized, "not_fqdn")
    return DomainDecision("allowed", normalized, "exact_domain")


def domain_matches(pattern: str, host: str) -> bool:
    normalized_pattern = normalize_domain(pattern)
    normalized_host = normalize_domain(host)
    if normalized_pattern.startswith("*."):
        suffix = normalized_pattern[1:]
        return normalized_host.endswith(suffix) and normalized_host != normalized_pattern[2:]
    return normalized_host == normalized_pattern


def _is_ip_literal(value: str) -> bool:
    candidate = value.strip("[]")
    try:
        ip = ipaddress.ip_address(candidate)
    except ValueError:
        return False
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip in _METADATA_IPS
    )


__all__ = [
    "DomainDecision",
    "domain_matches",
    "normalize_domain",
    "validate_domain_pattern",
]
