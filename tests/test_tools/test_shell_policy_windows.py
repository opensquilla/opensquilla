from __future__ import annotations

import pytest
import structlog.testing

from opensquilla.tools.builtin import shell_policy


@pytest.fixture(autouse=True)
def _windows_policy_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(shell_policy.os, "name", "nt")
    monkeypatch.delenv("OPENSQUILLA_SAFE_BIN_DENY", raising=False)
    monkeypatch.delenv("OPENSQUILLA_SAFE_BIN_ALLOW", raising=False)
    monkeypatch.delenv("OPENSQUILLA_SAFE_BIN_WARN", raising=False)
    monkeypatch.delenv("OPENSQUILLA_SHELL_DENYLIST", raising=False)
    monkeypatch.setattr(shell_policy, "_LEGACY_ENV_WARNED", False)


@pytest.mark.parametrize(
    "command",
    [
        r"del C:\Windows\System32\config\SAM",
        r"DEL C:\Windows\System32\config\SAM",
        r"dEl C:\Windows\System32\config\SAM",
    ],
)
def test_windows_del_variants_warn(command: str) -> None:
    result = shell_policy.SafeBinPolicy.from_env().check(command)

    assert result.allowed is True
    assert result.needs_approval is True
    assert "requires approval" in result.reason


@pytest.mark.parametrize(
    "command",
    [
        r"Remove-Item C:\tmp\stale.txt",
        r"remove-item C:\tmp\stale.txt",
        r"REMOVE-ITEM C:\tmp\stale.txt",
    ],
)
def test_windows_remove_item_variants_warn(command: str) -> None:
    result = shell_policy.SafeBinPolicy.from_env().check(command)

    assert result.allowed is True
    assert result.needs_approval is True
    assert "requires approval" in result.reason


def test_windows_rmdir_warns() -> None:
    result = shell_policy.SafeBinPolicy.from_env().check(r"rmdir C:\tmp\stale /S /Q")

    assert result.allowed is True
    assert result.needs_approval is True
    assert "requires approval" in result.reason


def test_windows_deny_env_overrides_platform_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENSQUILLA_SAFE_BIN_DENY", r"\bcustom-block\b")

    policy = shell_policy.SafeBinPolicy.from_env()

    custom = policy.check("custom-block")
    default_del = policy.check(r"del C:\Windows\System32\config\SAM")
    assert custom.allowed is False
    assert default_del.allowed is True
    assert default_del.needs_approval is True


def test_windows_empty_warn_env_clears_platform_default_warnlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENSQUILLA_SAFE_BIN_WARN", "")

    result = shell_policy.SafeBinPolicy.from_env().check(r"Remove-Item C:\tmp\stale.txt")

    assert result.allowed is True
    assert result.needs_approval is False


def test_windows_empty_warn_env_preserves_default_denylist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENSQUILLA_SAFE_BIN_WARN", "")

    result = shell_policy.SafeBinPolicy.from_env().check(r"Format-Volume -DriveLetter D")

    assert result.allowed is False
    assert result.needs_approval is False


def test_windows_disk_wipe_commands_stay_denied() -> None:
    result = shell_policy.SafeBinPolicy.from_env().check(r"Clear-Disk -Number 0")

    assert result.allowed is False
    assert result.needs_approval is False
    assert "blocked by policy" in result.reason


def test_legacy_shell_denylist_warns_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENSQUILLA_SHELL_DENYLIST", r"\blegacy-block\b")

    with structlog.testing.capture_logs() as captured:
        first = shell_policy.SafeBinPolicy.from_env()
        second = shell_policy.SafeBinPolicy.from_env()

    warnings = [
        event
        for event in captured
        if event["event"] == "shell_policy.legacy_deny_env_detected"
    ]
    assert len(warnings) == 1
    assert first.check("legacy-block").allowed is False
    assert second.check("legacy-block").allowed is False
