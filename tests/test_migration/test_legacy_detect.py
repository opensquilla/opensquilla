"""Shared legacy-home detection for the Phase 3 advisory surfaces.

``detect_legacy_home`` is consumed by the gateway boot warning, the doctor
``migration`` surface, and ``onboarding.status``; these tests pin its guard
behavior (never the live home, portable enumeration only where portable data
dirs can exist, never raises) and the suggested-command rendering.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

from opensquilla.migration import opensquilla_home
from opensquilla.migration.legacy_detect import (
    LegacyHomeCandidate,
    detect_legacy_home,
    suggested_migrate_command,
)


def _make_home(path: Path) -> Path:
    path.mkdir(parents=True)
    (path / "config.toml").write_text("port = 18790\n", encoding="utf-8")
    return path


@pytest.fixture()
def _no_portable_bases(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.delenv("TEMP", raising=False)


def test_detects_cli_home_when_target_is_elsewhere(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    _no_portable_bases: None,
) -> None:
    fake_home = tmp_path / "userhome"
    legacy = _make_home(fake_home / ".opensquilla")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

    candidate = detect_legacy_home(tmp_path / "electron-home")

    assert candidate == LegacyHomeCandidate(path=legacy, kind="cli-home")


def test_live_cli_home_is_never_offered(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    _no_portable_bases: None,
) -> None:
    fake_home = tmp_path / "userhome"
    legacy = _make_home(fake_home / ".opensquilla")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

    assert detect_legacy_home(legacy) is None


def test_default_target_honors_state_dir_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    _no_portable_bases: None,
) -> None:
    fake_home = tmp_path / "userhome"
    legacy = _make_home(fake_home / ".opensquilla")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

    # Relocated install (e.g. a desktop spawn): ~/.opensquilla is a candidate.
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(tmp_path / "relocated-home"))
    relocated = detect_legacy_home()
    assert relocated == LegacyHomeCandidate(path=legacy, kind="cli-home")

    # Default install: the target IS ~/.opensquilla, so nothing is offered.
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(legacy))
    assert detect_legacy_home() is None


def test_portable_fallback_offers_newest_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_home = tmp_path / "userhome"
    fake_home.mkdir()  # no ~/.opensquilla: the cli-home probe finds nothing
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    base = tmp_path / "appdata-local"
    older = _make_home(base / "OpenSquilla" / "portable" / "dummy-release-a")
    newer = _make_home(base / "OpenSquilla" / "portable" / "dummy-release-b")
    now = time.time()
    os.utime(older / "config.toml", (now - 1000, now - 1000))
    os.utime(newer / "config.toml", (now, now))
    monkeypatch.setenv("LOCALAPPDATA", str(base))
    monkeypatch.delenv("TEMP", raising=False)

    candidate = detect_legacy_home(tmp_path / "target-home")

    assert candidate == LegacyHomeCandidate(path=newer, kind="windows-portable")


def test_portable_candidate_that_is_the_target_is_skipped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_home = tmp_path / "userhome"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    base = tmp_path / "appdata-local"
    live = _make_home(base / "OpenSquilla" / "portable" / "dummy-release-a")
    monkeypatch.setenv("LOCALAPPDATA", str(base))
    monkeypatch.delenv("TEMP", raising=False)

    assert detect_legacy_home(live) is None


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only guard")
def test_portable_enumeration_is_skipped_without_base_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    _no_portable_bases: None,
) -> None:
    fake_home = tmp_path / "userhome"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    calls: list[object] = []
    monkeypatch.setattr(
        opensquilla_home,
        "enumerate_portable_homes",
        lambda bases=None: calls.append(bases) or [],
    )

    assert detect_legacy_home(tmp_path / "target-home") is None
    assert not calls


def test_detection_swallows_os_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _explode(target: Path) -> Path | None:
        raise OSError("disk unreadable")

    monkeypatch.setattr(opensquilla_home, "detect_legacy_cli_home", _explode)

    assert detect_legacy_home(tmp_path / "target-home") is None


def test_suggested_migrate_command_renders_kind_and_source() -> None:
    candidate = LegacyHomeCandidate(path=Path("/legacy/home"), kind="cli-home")

    assert suggested_migrate_command(candidate) == (
        "opensquilla migrate opensquilla --kind cli-home --source /legacy/home"
    )


def test_suggested_migrate_command_quotes_paths_with_spaces() -> None:
    candidate = LegacyHomeCandidate(
        path=Path("/legacy homes/data dir"), kind="windows-portable"
    )

    assert suggested_migrate_command(candidate) == (
        "opensquilla migrate opensquilla --kind windows-portable "
        "--source '/legacy homes/data dir'"
    )
