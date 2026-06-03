"""Network allowlist decisions for sandboxed tool traffic."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from opensquilla.sandbox.default_allowlist import default_allowlist_source
from opensquilla.sandbox.domain_validation import domain_matches, validate_domain_pattern
from opensquilla.sandbox.package_bundles import (
    DEFAULT_PACKAGE_BUNDLE_IDS,
    expand_package_bundle,
)
from opensquilla.sandbox.run_context import RunContext
from opensquilla.sandbox.run_mode import RunMode

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
    if context.run_mode == RunMode.FULL:
        return NetworkDecision(
            status="allow",
            normalized_host=normalized_host,
            reason="full_host_access",
            source="run_mode:full",
        )

    if "*" in normalized_host:
        return NetworkDecision(
            status="block",
            normalized_host=normalized_host,
            reason="invalid_domain",
            source="validation",
        )

    disabled_bundle_ids = {
        grant.bundle_id for grant in context.bundles if grant.source == "disabled"
    }
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
        if grant.source == "disabled":
            continue
        for bundled_domain in expand_package_bundle(grant.bundle_id):
            if domain_matches(bundled_domain, normalized_host):
                return NetworkDecision(
                    status="allow",
                    normalized_host=normalized_host,
                    reason="package_bundle",
                    source=f"bundle:{grant.bundle_id}",
                )

    if context.run_mode == RunMode.TRUSTED and _is_recognized_default_host(
        normalized_host,
        disabled_bundle_ids=disabled_bundle_ids,
    ):
        return NetworkDecision(
            status="allow",
            normalized_host=normalized_host,
            reason="auto_trusted",
            source="auto_trusted:chat",
        )

    default_source = default_allowlist_source(normalized_host)
    if default_source is not None:
        return NetworkDecision(
            status="allow",
            normalized_host=normalized_host,
            reason="default_allowlist",
            source=default_source,
        )

    for bundle_id in DEFAULT_PACKAGE_BUNDLE_IDS:
        if bundle_id in disabled_bundle_ids:
            continue
        for bundled_domain in expand_package_bundle(bundle_id):
            if domain_matches(bundled_domain, normalized_host):
                return NetworkDecision(
                    status="allow",
                    normalized_host=normalized_host,
                    reason="package_bundle",
                    source=f"bundle:{bundle_id}",
                )

    return NetworkDecision(
        status="ask",
        normalized_host=normalized_host,
        reason="unknown_domain",
        source=None,
    )


def _is_recognized_default_host(
    normalized_host: str,
    *,
    disabled_bundle_ids: set[str],
) -> bool:
    if default_allowlist_source(normalized_host) is not None:
        return True
    return any(
        domain_matches(bundled_domain, normalized_host)
        for bundle_id in DEFAULT_PACKAGE_BUNDLE_IDS
        if bundle_id not in disabled_bundle_ids
        for bundled_domain in expand_package_bundle(bundle_id)
    )


__all__ = ["NetworkDecision", "NetworkDecisionStatus", "decide_network_access"]
