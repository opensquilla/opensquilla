"""Routing policy: pure post-classifier heuristic stages.

The squilla-router step classifies a turn; the policy in this package
decides the final tier from that classification plus turn facts. See
:mod:`opensquilla.engine.routing.policy` for the stage definitions and the
orchestrating :class:`~opensquilla.engine.routing.policy.RoutingPolicyEngine`.
"""

from __future__ import annotations

from opensquilla.engine.routing.policy import (
    AntiDowngradeResult,
    ComplaintUpgradeResult,
    ConfidenceGateResult,
    PolicyInputs,
    PolicyResult,
    ProviderMismatchOutcome,
    RoutingDecision,
    RoutingPolicyEngine,
    anti_downgrade,
    bind,
    complaint_upgrade,
    confidence_gate,
    detect_complaint,
    large_context_floor,
    large_context_min_tier,
    previous_final_entry,
    previous_final_tier,
    provider_mismatch,
    reconcile_controller_with_final_tier,
    route_class_for_tier,
    tier_for_route_class,
)

__all__ = [
    "AntiDowngradeResult",
    "ComplaintUpgradeResult",
    "ConfidenceGateResult",
    "PolicyInputs",
    "PolicyResult",
    "ProviderMismatchOutcome",
    "RoutingDecision",
    "RoutingPolicyEngine",
    "anti_downgrade",
    "bind",
    "complaint_upgrade",
    "confidence_gate",
    "detect_complaint",
    "large_context_floor",
    "large_context_min_tier",
    "previous_final_entry",
    "previous_final_tier",
    "provider_mismatch",
    "reconcile_controller_with_final_tier",
    "route_class_for_tier",
    "tier_for_route_class",
]
