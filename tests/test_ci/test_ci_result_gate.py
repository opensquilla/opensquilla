from __future__ import annotations

import runpy
from typing import Any

GATE_MODULE: dict[str, Any] = runpy.run_path(
    ".github/scripts/check_ci_results.py", run_name="check_ci_results"
)
BOOLEAN_FLAGS: tuple[str, ...] = GATE_MODULE["BOOLEAN_FLAGS"]
check_ci_results = GATE_MODULE["check_ci_results"]


def _flag_env(name: str) -> str:
    return f"FLAG_{name.upper()}"


def _base_env() -> dict[str, str]:
    env = {
        "RESULT_CLASSIFY": "success",
        "RESULT_WORKFLOW_LINT": "success",
        "RESULT_README_LOCALE": "success",
        "RESULT_FRONTEND": "skipped",
        "RESULT_TUI": "skipped",
        "RESULT_DESKTOP": "skipped",
        "RESULT_UBUNTU": "skipped",
        "RESULT_WINDOWS_SMOKE": "skipped",
        "RESULT_WINDOWS_FULL": "skipped",
        "RESULT_RELEASE": "skipped",
    }
    env.update({_flag_env(name): "false" for name in BOOLEAN_FLAGS})
    env[_flag_env("docs_only")] = "true"
    return env


def _full_env() -> dict[str, str]:
    env = _base_env()
    env.update({_flag_env(name): "true" for name in BOOLEAN_FLAGS})
    env[_flag_env("docs_only")] = "false"
    for key in tuple(env):
        if key.startswith("RESULT_"):
            env[key] = "success"
    return env


def test_ci_result_gate_accepts_intentional_docs_only_skips() -> None:
    assert check_ci_results(_base_env()) == []


def test_ci_result_gate_accepts_complete_full_matrix() -> None:
    assert check_ci_results(_full_env()) == []


def test_ci_result_gate_rejects_missing_or_invalid_classifier_outputs() -> None:
    missing = _base_env()
    missing.pop(_flag_env("windows_full_required"))
    invalid = _base_env()
    invalid[_flag_env("python_changed")] = "yes"

    assert any("windows_full_required" in error for error in check_ci_results(missing))
    assert any("python_changed" in error for error in check_ci_results(invalid))


def test_ci_result_gate_rejects_required_windows_matrix_skip() -> None:
    env = _base_env()
    env[_flag_env("docs_only")] = "false"
    env[_flag_env("runtime_changed")] = "true"
    env[_flag_env("python_changed")] = "true"
    env[_flag_env("platform_sensitive_changed")] = "true"
    env[_flag_env("windows_full_required")] = "true"
    env[_flag_env("build_wheel_required")] = "true"
    env["RESULT_UBUNTU"] = "success"
    env["RESULT_WINDOWS_SMOKE"] = "success"

    errors = check_ci_results(env)

    assert any("Windows high-risk matrix" in error and "skipped" in error for error in errors)


def test_ci_result_gate_rejects_failure_cancellation_and_missing_results() -> None:
    for result in ("failure", "cancelled", ""):
        env = _full_env()
        env["RESULT_WINDOWS_FULL"] = result

        errors = check_ci_results(env)

        assert any("Windows high-risk matrix" in error for error in errors)


def test_ci_result_gate_rejects_inconsistent_full_and_platform_flags() -> None:
    incomplete_full = _full_env()
    incomplete_full[_flag_env("release_changed")] = "false"
    unsafe_platform = _base_env()
    unsafe_platform[_flag_env("docs_only")] = "false"
    unsafe_platform[_flag_env("platform_sensitive_changed")] = "true"

    assert any("release_changed=true" in error for error in check_ci_results(incomplete_full))
    assert any("Platform-sensitive" in error for error in check_ci_results(unsafe_platform))
