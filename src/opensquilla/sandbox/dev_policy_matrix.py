"""Central policy matrix for trusted sandbox development recovery."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from opensquilla.sandbox.capability_profile import CapabilityProfile, NetworkIntent
from opensquilla.sandbox.run_mode import RunMode, normalize_run_mode


class PathTargetClass(StrEnum):
    WORKSPACE = "workspace"
    TEMP = "temp"
    NORMAL_USER_PATH = "normal_user_path"
    UNCLEAR = "unclear"
    SENSITIVE = "sensitive"


class NetworkTargetClass(StrEnum):
    NONE = "none"
    KNOWN_PACKAGE_REGISTRY = "known_package_registry"
    SOURCE_FETCH = "source_fetch"
    UNKNOWN_PUBLIC = "unknown_public"
    PRIVATE_OR_LOCAL = "private_or_local"
    METADATA_OR_LINK_LOCAL = "metadata_or_link_local"


class DevPolicyDecisionKind(StrEnum):
    AUTO = "auto"
    ASK = "ask"
    DENY = "deny"
    NO_MATCH = "no_match"


@dataclass(frozen=True)
class DevPolicyDecision:
    kind: DevPolicyDecisionKind
    reason: str
    use_managed_proxy: bool = False
    grant_rw_path: bool = False
    retry_once: bool = False


_SAFE_TRUSTED_PATHS = {
    PathTargetClass.WORKSPACE,
    PathTargetClass.TEMP,
    PathTargetClass.NORMAL_USER_PATH,
}

_SAFE_TRUSTED_NETWORKS = {
    NetworkTargetClass.NONE,
    NetworkTargetClass.KNOWN_PACKAGE_REGISTRY,
    NetworkTargetClass.SOURCE_FETCH,
    NetworkTargetClass.UNKNOWN_PUBLIC,
}

_UNSAFE_NETWORKS = {
    NetworkTargetClass.PRIVATE_OR_LOCAL,
    NetworkTargetClass.METADATA_OR_LINK_LOCAL,
}

_UNSAFE_NETWORK_INTENTS = {
    NetworkIntent.PRIVATE_OR_LOCAL,
    NetworkIntent.METADATA_OR_LINK_LOCAL,
}


def _normalize_path_class(value: PathTargetClass | str) -> PathTargetClass | None:
    try:
        return PathTargetClass(value)
    except ValueError:
        return None


def _normalize_network_class(
    value: NetworkTargetClass | str,
) -> NetworkTargetClass | None:
    try:
        return NetworkTargetClass(value)
    except ValueError:
        return None


def decide_dev_recovery(
    run_mode: RunMode | str,
    profile: CapabilityProfile,
    path_class: PathTargetClass | str,
    network_class: NetworkTargetClass | str,
) -> DevPolicyDecision:
    if not profile.is_development_operation:
        return DevPolicyDecision(
            DevPolicyDecisionKind.NO_MATCH,
            "not_development_operation",
        )

    normalized_path_class = _normalize_path_class(path_class)
    normalized_network_class = _normalize_network_class(network_class)

    if normalized_path_class is None or normalized_network_class is None:
        return DevPolicyDecision(DevPolicyDecisionKind.ASK, "unclear_target")

    if profile.sensitive_path_touch:
        return DevPolicyDecision(DevPolicyDecisionKind.DENY, "sensitive_path")

    if normalized_path_class is PathTargetClass.SENSITIVE:
        return DevPolicyDecision(DevPolicyDecisionKind.DENY, "sensitive_path")

    if (
        normalized_network_class in _UNSAFE_NETWORKS
        or profile.network_intent in _UNSAFE_NETWORK_INTENTS
    ):
        return DevPolicyDecision(DevPolicyDecisionKind.DENY, "unsafe_network_target")

    mode = normalize_run_mode(run_mode)
    needs_network = (
        profile.needs_network
        or normalized_network_class is not NetworkTargetClass.NONE
    )

    if mode is RunMode.FULL:
        return DevPolicyDecision(DevPolicyDecisionKind.AUTO, "full_host_mode")

    if mode is RunMode.STANDARD:
        return DevPolicyDecision(
            DevPolicyDecisionKind.ASK,
            "standard_requires_approval",
            use_managed_proxy=needs_network,
        )

    if (
        mode is RunMode.TRUSTED
        and normalized_path_class in _SAFE_TRUSTED_PATHS
        and normalized_network_class in _SAFE_TRUSTED_NETWORKS
    ):
        return DevPolicyDecision(
            DevPolicyDecisionKind.AUTO,
            "trusted_development_operation",
            use_managed_proxy=needs_network,
            grant_rw_path=normalized_path_class is not PathTargetClass.WORKSPACE,
            retry_once=True,
        )

    return DevPolicyDecision(DevPolicyDecisionKind.ASK, "unclear_target")


__all__ = [
    "DevPolicyDecision",
    "DevPolicyDecisionKind",
    "NetworkTargetClass",
    "PathTargetClass",
    "decide_dev_recovery",
]
