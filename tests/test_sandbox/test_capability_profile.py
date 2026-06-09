from __future__ import annotations

from opensquilla.sandbox.capability_profile import (
    Capability,
    Confidence,
    NetworkIntent,
    capability_profile_for_command,
)


def test_pip_install_maps_to_install_packages_capability() -> None:
    profile = capability_profile_for_command(
        ("sh", "-lc", "python -m pip install --no-cache-dir httpx")
    )

    assert Capability.INSTALL_PACKAGES in profile.capabilities
    assert profile.package_ecosystem == "python"
    assert profile.network_intent is NetworkIntent.PACKAGE_REGISTRY
    assert profile.may_run_build_scripts is True
    assert profile.confidence is Confidence.HIGH
    assert "python-package-install" in profile.package_bundles


def test_venv_then_install_merges_create_env_and_install_packages() -> None:
    profile = capability_profile_for_command(
        (
            "sh",
            "-lc",
            "python -m venv /tmp/proj/.venv && "
            "/tmp/proj/.venv/bin/python -m pip install requests",
        )
    )

    assert Capability.CREATE_ENV in profile.capabilities
    assert Capability.INSTALL_PACKAGES in profile.capabilities
    assert profile.package_ecosystem == "python"
    assert "/tmp/proj/.venv" in profile.write_paths


def test_venv_option_is_skipped_when_parsing_venv_path() -> None:
    profile = capability_profile_for_command(
        (
            "sh",
            "-lc",
            "python -m venv --clear /tmp/proj/.venv && "
            "/tmp/proj/.venv/bin/python -m pip install requests",
        )
    )

    assert Capability.CREATE_ENV in profile.capabilities
    assert Capability.INSTALL_PACKAGES in profile.capabilities
    assert "/tmp/proj/.venv" in profile.write_paths
    assert "--clear" not in profile.write_paths


def test_unknown_command_keeps_low_confidence_without_network_intent() -> None:
    profile = capability_profile_for_command(("sh", "-lc", "echo hello"))

    assert profile.capabilities == frozenset()
    assert profile.package_ecosystem is None
    assert profile.network_intent is None
    assert profile.confidence is Confidence.LOW
