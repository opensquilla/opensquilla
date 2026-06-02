"""Domain normalization and safety checks for sandbox managed network."""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlparse

DomainStatus = Literal["allowed", "blocked"]


@dataclass(frozen=True)
class DomainDecision:
    status: DomainStatus
    normalized: str
    reason: str


_BROAD_WILDCARD_SUFFIXES = {
    "com",
    "org",
    "net",
    "io",
    "dev",
    "co.uk",
    "github.io",
    "pages.dev",
    "appspot.com",
    "cloudfront.net",
    "herokuapp.com",
    "netlify.app",
    "vercel.app",
}

_DNS_LABEL_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789-")
_IPV4_NUMERIC_ALIAS_RE = re.compile(r"\d+(?:\.\d+){1,3}")


def normalize_domain(raw: str) -> str:
    text = str(raw or "").strip().lower()
    if not text:
        return ""
    if "://" in text:
        parsed = urlparse(text)
        text = parsed.hostname or ""
    else:
        text = text.split("/", 1)[0]
        if text.startswith("["):
            bracket_end = text.find("]")
            text = text[: bracket_end + 1] if bracket_end != -1 else text
        elif text.count(":") == 1:
            text = text.split(":", 1)[0]
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
        if not _is_valid_dns_name(suffix):
            return DomainDecision("blocked", normalized, "invalid_domain")
        if suffix in _BROAD_WILDCARD_SUFFIXES:
            return DomainDecision("blocked", normalized, "broad_wildcard")
        return DomainDecision("allowed", normalized, "wildcard_domain")
    if "*" in normalized:
        return DomainDecision("blocked", normalized, "invalid_wildcard")
    if "." not in normalized:
        return DomainDecision("blocked", normalized, "not_fqdn")
    if not _is_valid_dns_name(normalized):
        return DomainDecision("blocked", normalized, "invalid_domain")
    return DomainDecision("allowed", normalized, "exact_domain")


def domain_matches(pattern: str, host: str) -> bool:
    decision = validate_domain_pattern(pattern)
    if decision.status != "allowed":
        return False
    normalized_pattern = decision.normalized
    normalized_host = normalize_domain(host)
    if _is_ip_literal(normalized_host) or not _is_valid_dns_name(normalized_host):
        return False
    if normalized_pattern.startswith("*."):
        suffix = normalized_pattern[2:]
        return normalized_host.endswith(f".{suffix}")
    return normalized_host == normalized_pattern


def _is_valid_dns_name(value: str) -> bool:
    if not value or len(value) > 253:
        return False
    labels = value.split(".")
    for label in labels:
        if not label or len(label) > 63:
            return False
        if label.startswith("-") or label.endswith("-"):
            return False
        if any(char not in _DNS_LABEL_CHARS for char in label):
            return False
    return True


def _is_ip_literal(value: str) -> bool:
    candidate = value.strip("[]")
    try:
        ipaddress.ip_address(candidate)
    except ValueError:
        return _IPV4_NUMERIC_ALIAS_RE.fullmatch(candidate) is not None
    return True


__all__ = [
    "DomainDecision",
    "domain_matches",
    "normalize_domain",
    "validate_domain_pattern",
]
