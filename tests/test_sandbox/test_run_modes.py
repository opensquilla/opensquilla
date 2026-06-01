from __future__ import annotations

import types

from opensquilla.sandbox.run_mode import (
    RunMode,
    approval_behavior,
    execution_target,
    legacy_state_to_run_mode,
    normalize_run_mode,
    run_mode_config_patch,
)


def test_trusted_sandbox_is_sandboxed_and_skips_only_routine_prompts() -> None:
    patch = run_mode_config_patch(RunMode.TRUSTED)

    assert patch.sandbox is True
    assert patch.security_grading is True
    assert patch.permissions_default_mode == "off"
    assert execution_target(RunMode.TRUSTED) == "sandbox"
    assert approval_behavior(RunMode.TRUSTED) == "trusted"


def test_full_host_access_is_the_only_global_host_target() -> None:
    assert execution_target(RunMode.STANDARD) == "sandbox"
    assert execution_target(RunMode.TRUSTED) == "sandbox"
    assert execution_target(RunMode.FULL) == "host"


def test_legacy_bypass_state_maps_to_trusted_without_preserving_host_bypass() -> None:
    mode = legacy_state_to_run_mode(
        sandbox_enabled=False,
        grading_enabled=False,
        permissions_default_mode="bypass",
    )

    assert mode == RunMode.TRUSTED


def test_configured_default_elevated_only_returns_full() -> None:
    from opensquilla.permissions import configured_default_elevated, configured_default_run_mode

    config = types.SimpleNamespace(
        sandbox=types.SimpleNamespace(run_mode="trusted", sandbox=True, security_grading=True),
        permissions=types.SimpleNamespace(default_mode="off"),
    )

    assert configured_default_run_mode(config) == RunMode.TRUSTED
    assert configured_default_elevated(config) is None

    config.sandbox.run_mode = "full"
    assert configured_default_run_mode(config) == RunMode.FULL
    assert configured_default_elevated(config) == "full"


def test_normalize_run_mode_accepts_user_facing_spellings() -> None:
    assert normalize_run_mode("standard-sandbox") == RunMode.STANDARD
    assert normalize_run_mode("trusted") == RunMode.TRUSTED
    assert normalize_run_mode("full-host-access") == RunMode.FULL
