from __future__ import annotations

import subprocess
from pathlib import Path

from opensquilla.sandbox.backend import linux_readiness as mod


def test_detects_wsl1_from_proc_version() -> None:
    assert mod.proc_version_indicates_wsl1("Linux version 4.4.0 Microsoft")
    assert not mod.proc_version_indicates_wsl1("Linux version 5.15.90.1-microsoft-standard-WSL2")


def test_user_namespace_failure_patterns() -> None:
    output = subprocess.CompletedProcess(
        args=["bwrap"],
        returncode=1,
        stdout=b"",
        stderr=b"bwrap: No permissions to create a new namespace\n",
    )

    assert mod.is_user_namespace_failure(output)


def test_probe_reports_missing_bwrap(monkeypatch) -> None:
    monkeypatch.setattr(mod.shutil, "which", lambda name: None)
    monkeypatch.setattr(mod, "is_wsl1", lambda: False)

    probe = mod.probe_bwrap()

    assert not probe.available
    assert probe.reason == "missing_bwrap"
    assert "bubblewrap" in probe.message.lower()


def test_probe_reports_user_namespace_unavailable(monkeypatch, tmp_path: Path) -> None:
    fake_bwrap = tmp_path / "bwrap"
    fake_bwrap.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(mod.shutil, "which", lambda name: str(fake_bwrap))
    monkeypatch.setattr(mod, "is_wsl1", lambda: False)
    def fake_run(argv, **kwargs):
        if "--help" in argv:
            return subprocess.CompletedProcess(
                args=argv,
                returncode=0,
                stdout=b"--perms\n",
                stderr=b"",
            )
        return subprocess.CompletedProcess(
            args=argv,
            returncode=1,
            stdout=b"",
            stderr=b"No permissions to create a new namespace",
        )

    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    probe = mod.probe_bwrap()

    assert not probe.available
    assert probe.reason == "user_namespace_unavailable"


def test_probe_reports_supported_bwrap(monkeypatch, tmp_path: Path) -> None:
    fake_bwrap = tmp_path / "bwrap"
    fake_bwrap.write_text("#!/bin/sh\n", encoding="utf-8")
    calls: list[list[str]] = []

    def fake_run(argv, **kwargs):
        calls.append(list(argv))
        if "--help" in argv:
            return subprocess.CompletedProcess(
                args=argv,
                returncode=0,
                stdout=b"--argv0\n--perms\n",
                stderr=b"",
            )
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(mod.shutil, "which", lambda name: str(fake_bwrap))
    monkeypatch.setattr(mod, "is_wsl1", lambda: False)
    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    probe = mod.probe_bwrap()

    assert probe.available
    assert probe.path == str(fake_bwrap)
    assert probe.supports_argv0 is True
    assert probe.supports_perms is True
    assert probe.supports_proc is True
    assert calls[0] == [str(fake_bwrap), "--help"]


def test_probe_rejects_bwrap_without_required_perms_support(monkeypatch, tmp_path: Path) -> None:
    fake_bwrap = tmp_path / "bwrap"
    fake_bwrap.write_text("#!/bin/sh\n", encoding="utf-8")

    def fake_run(argv, **kwargs):
        if "--help" in argv:
            return subprocess.CompletedProcess(
                args=argv,
                returncode=0,
                stdout=b"--argv0\n",
                stderr=b"",
            )
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(mod.shutil, "which", lambda name: str(fake_bwrap))
    monkeypatch.setattr(mod, "is_wsl1", lambda: False)
    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    probe = mod.probe_bwrap()

    assert not probe.available
    assert probe.reason == "missing_bwrap_perms"
    assert probe.supports_perms is False


def test_probe_reports_available_bwrap_without_proc_mount_support(
    monkeypatch,
    tmp_path: Path,
) -> None:
    fake_bwrap = tmp_path / "bwrap"
    fake_bwrap.write_text("#!/bin/sh\n", encoding="utf-8")
    calls: list[list[str]] = []

    def fake_run(argv, **kwargs):
        calls.append(list(argv))
        if "--help" in argv:
            return subprocess.CompletedProcess(
                args=argv,
                returncode=0,
                stdout=b"--argv0\n--perms\n",
                stderr=b"",
            )
        if "--proc" in argv:
            return subprocess.CompletedProcess(
                args=argv,
                returncode=1,
                stdout=b"",
                stderr=b"bwrap: Can't mount proc on /newroot/proc: Operation not permitted",
            )
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(mod.shutil, "which", lambda name: str(fake_bwrap))
    monkeypatch.setattr(mod, "is_wsl1", lambda: False)
    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    probe = mod.probe_bwrap()

    assert probe.available
    assert probe.reason == "ready"
    assert probe.supports_proc is False
    assert any("--proc" in call for call in calls)
