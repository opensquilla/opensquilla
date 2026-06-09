from __future__ import annotations

from opensquilla.sandbox.capability_profile import (
    Capability,
    CapabilityProfile,
    NetworkIntent,
)
from opensquilla.sandbox.dev_policy_matrix import (
    DevPolicyDecisionKind,
    NetworkTargetClass,
    PathTargetClass,
    decide_dev_recovery,
)
from opensquilla.sandbox.run_mode import RunMode


def _install_profile(network_intent: NetworkIntent | None = None) -> CapabilityProfile:
    return CapabilityProfile(
        capabilities=frozenset({Capability.INSTALL_PACKAGES}),
        network_intent=network_intent,
    )


def test_trusted_install_to_normal_path_auto_allows_managed_proxy_and_rw_grant() -> None:
    decision = decide_dev_recovery(
        RunMode.TRUSTED,
        _install_profile(NetworkIntent.PACKAGE_REGISTRY),
        PathTargetClass.NORMAL_USER_PATH,
        NetworkTargetClass.KNOWN_PACKAGE_REGISTRY,
    )

    assert decision.kind is DevPolicyDecisionKind.AUTO
    assert decision.reason == "trusted_development_operation"
    assert decision.use_managed_proxy is True
    assert decision.grant_rw_path is True
    assert decision.retry_once is True


def test_standard_install_asks_and_does_not_grant_rw_path() -> None:
    decision = decide_dev_recovery(
        RunMode.STANDARD,
        _install_profile(NetworkIntent.PACKAGE_REGISTRY),
        PathTargetClass.NORMAL_USER_PATH,
        NetworkTargetClass.KNOWN_PACKAGE_REGISTRY,
    )

    assert decision.kind is DevPolicyDecisionKind.ASK
    assert decision.reason == "standard_requires_approval"
    assert decision.use_managed_proxy is True
    assert decision.grant_rw_path is False


def test_trusted_sensitive_path_denies() -> None:
    decision = decide_dev_recovery(
        RunMode.TRUSTED,
        _install_profile(),
        PathTargetClass.SENSITIVE,
        NetworkTargetClass.NONE,
    )

    assert decision.kind is DevPolicyDecisionKind.DENY
    assert decision.reason == "sensitive_path"


def test_trusted_private_or_local_network_denies() -> None:
    decision = decide_dev_recovery(
        RunMode.TRUSTED,
        _install_profile(NetworkIntent.PRIVATE_OR_LOCAL),
        PathTargetClass.NORMAL_USER_PATH,
        NetworkTargetClass.PRIVATE_OR_LOCAL,
    )

    assert decision.kind is DevPolicyDecisionKind.DENY
    assert decision.reason == "unsafe_network_target"


def test_non_development_command_returns_no_match() -> None:
    decision = decide_dev_recovery(
        RunMode.TRUSTED,
        CapabilityProfile(),
        PathTargetClass.NORMAL_USER_PATH,
        NetworkTargetClass.NONE,
    )

    assert decision.kind is DevPolicyDecisionKind.NO_MATCH
    assert decision.reason == "not_development_operation"


def test_trusted_workspace_path_does_not_grant_rw_path() -> None:
    decision = decide_dev_recovery(
        RunMode.TRUSTED,
        _install_profile(),
        PathTargetClass.WORKSPACE,
        NetworkTargetClass.NONE,
    )

    assert decision.kind is DevPolicyDecisionKind.AUTO
    assert decision.reason == "trusted_development_operation"
    assert decision.grant_rw_path is False
    assert decision.retry_once is True


def test_profile_sensitive_path_touch_denies_even_when_path_class_is_normal() -> None:
    profile = CapabilityProfile(
        capabilities=frozenset({Capability.INSTALL_PACKAGES}),
        sensitive_path_touch=True,
    )

    decision = decide_dev_recovery(
        RunMode.TRUSTED,
        profile,
        PathTargetClass.NORMAL_USER_PATH,
        NetworkTargetClass.NONE,
    )

    assert decision.kind is DevPolicyDecisionKind.DENY
    assert decision.reason == "sensitive_path"


def test_profile_network_intent_requires_managed_proxy_even_when_network_class_none() -> None:
    decision = decide_dev_recovery(
        RunMode.TRUSTED,
        _install_profile(NetworkIntent.PACKAGE_REGISTRY),
        PathTargetClass.NORMAL_USER_PATH,
        NetworkTargetClass.NONE,
    )

    assert decision.kind is DevPolicyDecisionKind.AUTO
    assert decision.use_managed_proxy is True


def test_string_class_values_normalize() -> None:
    workspace_decision = decide_dev_recovery(
        RunMode.TRUSTED,
        _install_profile(),
        "workspace",
        "none",
    )
    sensitive_decision = decide_dev_recovery(
        RunMode.TRUSTED,
        _install_profile(),
        "sensitive",
        "none",
    )

    assert workspace_decision.kind is DevPolicyDecisionKind.AUTO
    assert workspace_decision.grant_rw_path is False
    assert sensitive_decision.kind is DevPolicyDecisionKind.DENY
    assert sensitive_decision.reason == "sensitive_path"


def test_invalid_class_values_do_not_auto_allow() -> None:
    invalid_path_decision = decide_dev_recovery(
        RunMode.TRUSTED,
        _install_profile(),
        "not-a-path-class",
        "none",
    )
    invalid_network_decision = decide_dev_recovery(
        RunMode.TRUSTED,
        _install_profile(),
        "workspace",
        "not-a-network-class",
    )

    assert invalid_path_decision.kind is DevPolicyDecisionKind.ASK
    assert invalid_path_decision.reason == "unclear_target"
    assert invalid_network_decision.kind is DevPolicyDecisionKind.ASK
    assert invalid_network_decision.reason == "unclear_target"
