"""Network allowlist decisions for sandboxed tool traffic."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from opensquilla.sandbox.domain_validation import domain_matches, validate_domain_pattern
from opensquilla.sandbox.package_bundles import expand_package_bundle
from opensquilla.sandbox.run_context import RunContext

NetworkDecisionStatus = Literal["allow", "ask", "block"]


@dataclass(frozen=True)
class NetworkDecision:
    status: NetworkDecisionStatus
    normalized_host: str
    reason: str
    source: str | None


def decide_network_access(host: str, context: RunContext) -> NetworkDecision:
    validation = validate_domain_pattern(host)
    if validation.status == "blocked":
        return NetworkDecision(
            status="block",
            normalized_host=validation.normalized,
            reason=validation.reason,
            source="validation",
        )

    normalized_host = validation.normalized
    if "*" in normalized_host:
        return NetworkDecision(
            status="block",
            normalized_host=normalized_host,
            reason="invalid_domain",
            source="validation",
        )

    for grant in context.domains:
        if domain_matches(grant.domain, normalized_host):
            grant_validation = validate_domain_pattern(grant.domain)
            reason = "system_domain_grant" if grant.source == "system" else "domain_grant"
            source_prefix = "system" if grant.source == "system" else "domain"
            return NetworkDecision(
                status="allow",
                normalized_host=normalized_host,
                reason=reason,
                source=f"{source_prefix}:{grant_validation.normalized}",
            )

    for grant in context.bundles:
        for bundled_domain in expand_package_bundle(grant.bundle_id):
            if domain_matches(bundled_domain, normalized_host):
                return NetworkDecision(
                    status="allow",
                    normalized_host=normalized_host,
                    reason="package_bundle",
                    source=f"bundle:{grant.bundle_id}",
                )

    return NetworkDecision(
        status="ask",
        normalized_host=normalized_host,
        reason="unknown_domain",
        source=None,
    )


__all__ = ["NetworkDecision", "NetworkDecisionStatus", "decide_network_access"]
