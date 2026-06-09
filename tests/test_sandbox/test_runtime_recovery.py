from __future__ import annotations

from opensquilla.sandbox.capability_profile import capability_profile_for_command
from opensquilla.sandbox.dev_policy_matrix import NetworkTargetClass
from opensquilla.sandbox.runtime_recovery import (
    RecoveryFailureKind,
    classify_network_failure,
    network_class_for_failure,
)


def test_dns_failure_extracts_curl_host() -> None:
    failure = classify_network_failure("curl: (6) Could not resolve host: pypi.org\n")

    assert failure is not None
    assert failure.kind is RecoveryFailureKind.DNS_FAILURE
    assert failure.host == "pypi.org"
    assert "Could not resolve host" in failure.evidence


def test_private_localhost_target_becomes_private_or_local() -> None:
    profile = capability_profile_for_command(("sh", "-lc", "curl http://127.0.0.1:8000"))

    assert (
        network_class_for_failure("127.0.0.1", profile=profile, default=NetworkTargetClass.NONE)
        is NetworkTargetClass.PRIVATE_OR_LOCAL
    )


def test_link_local_metadata_target_becomes_metadata_or_link_local() -> None:
    profile = capability_profile_for_command(("sh", "-lc", "curl http://169.254.169.254/"))

    assert (
        network_class_for_failure(
            "169.254.169.254",
            profile=profile,
            default=NetworkTargetClass.NONE,
        )
        is NetworkTargetClass.METADATA_OR_LINK_LOCAL
    )


def test_public_package_registry_profile_becomes_known_package_registry() -> None:
    profile = capability_profile_for_command(("sh", "-lc", "pip install demo"))

    assert (
        network_class_for_failure("pypi.org", profile=profile, default=NetworkTargetClass.NONE)
        is NetworkTargetClass.KNOWN_PACKAGE_REGISTRY
    )
