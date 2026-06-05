from __future__ import annotations

from pathlib import Path

from opensquilla.sandbox.config import SandboxSettings
from opensquilla.sandbox.policy import build_policy
from opensquilla.sandbox.types import NetworkMode, SecurityLevel


def test_standard_network_http_keeps_host_network(tmp_path: Path) -> None:
    policy = build_policy(
        SecurityLevel.STANDARD,
        "network.http",
        tmp_path,
        SandboxSettings(),
        trusted=True,
    )

    assert policy.network is NetworkMode.HOST


def test_standard_shell_and_code_exec_keep_network_none(tmp_path: Path) -> None:
    settings = SandboxSettings()

    shell_policy = build_policy(
        SecurityLevel.STANDARD,
        "shell.exec",
        tmp_path,
        settings,
        trusted=True,
    )
    code_policy = build_policy(
        SecurityLevel.STANDARD,
        "code.exec",
        tmp_path,
        settings,
        trusted=True,
    )

    assert shell_policy.network is NetworkMode.NONE
    assert code_policy.network is NetworkMode.NONE


def test_shell_exec_policy_allows_meta_skill_workspace_env(tmp_path: Path) -> None:
    policy = build_policy(
        SecurityLevel.STANDARD,
        "shell.exec",
        tmp_path,
        SandboxSettings(),
        trusted=True,
    )

    assert "WORKSPACE_DIR" in policy.env_allowlist
    assert "PROJECT_ROOT" in policy.env_allowlist
