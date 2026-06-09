from __future__ import annotations

from pathlib import Path

from opensquilla.sandbox.capability_profile import capability_profile_for_command
from opensquilla.sandbox.dev_policy_matrix import NetworkTargetClass, PathTargetClass
from opensquilla.sandbox.runtime_recovery import (
    RecoveryFailureKind,
    classify_network_failure,
    classify_path_target,
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


def test_metadata_command_target_overrides_hostless_network_failure() -> None:
    profile = capability_profile_for_command(("sh", "-lc", "curl http://169.254.169.254/"))

    assert (
        network_class_for_failure(
            None,
            profile=profile,
            default=NetworkTargetClass.UNKNOWN_PUBLIC,
            explicit_hosts=("169.254.169.254",),
        )
        is NetworkTargetClass.METADATA_OR_LINK_LOCAL
    )


def test_private_command_target_overrides_hostless_network_failure() -> None:
    profile = capability_profile_for_command(("sh", "-lc", "curl http://127.0.0.1:8000"))

    assert (
        network_class_for_failure(
            None,
            profile=profile,
            default=NetworkTargetClass.UNKNOWN_PUBLIC,
            explicit_hosts=("127.0.0.1",),
        )
        is NetworkTargetClass.PRIVATE_OR_LOCAL
    )


def test_user_project_path_outside_workspace_is_normal_user_path(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    project = Path.home() / ".cache" / "opensquilla-test-project"
    workspace.mkdir()

    assert (
        classify_path_target(project, workspace=workspace)
        is PathTargetClass.NORMAL_USER_PATH
    )


def test_workspace_child_is_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    child = workspace / "child"

    assert classify_path_target(child, workspace=workspace) is PathTargetClass.WORKSPACE


def test_sensitive_paths_are_sensitive() -> None:
    assert classify_path_target(Path("/etc/passwd"), workspace=None) is PathTargetClass.SENSITIVE
    assert (
        classify_path_target(Path.home() / ".ssh" / "id_rsa", workspace=None)
        is PathTargetClass.SENSITIVE
    )


def test_tmp_descendant_is_temp() -> None:
    assert classify_path_target(Path("/tmp/something"), workspace=None) is PathTargetClass.TEMP


def test_existing_user_owned_tmp_descendant_is_temp(tmp_path: Path) -> None:
    target = tmp_path / "existing"
    target.mkdir()

    assert classify_path_target(target, workspace=None) is PathTargetClass.TEMP
