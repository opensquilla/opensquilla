"""Migration-directory resolution: unusable env overrides must be loud.

``OPENSQUILLA_MIGRATIONS_DIR`` pointing at a missing directory (or one with
no ``V*.py`` files) used to fall through silently to a different migration
set — the operator believes a pinned set is in effect while another one
runs. The fallback behavior stays (boot should not die on a typo), but it
must be logged.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import structlog

from opensquilla.gateway.boot import _resolve_migrations_dir


def _env_ignored_events(captured: list[dict]) -> list[dict]:
    return [
        entry
        for entry in captured
        if entry.get("event") == "resolve_migrations_dir.env_override_ignored"
    ]


def test_missing_env_dir_warns_and_falls_through(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    missing = tmp_path / "does-not-exist"
    monkeypatch.setenv("OPENSQUILLA_MIGRATIONS_DIR", str(missing))
    with structlog.testing.capture_logs() as captured:
        resolved = _resolve_migrations_dir()
    assert resolved != missing
    assert any(resolved.glob("V*.py"))  # fell through to a usable set
    events = _env_ignored_events(captured)
    assert len(events) == 1
    assert events[0]["path"] == str(missing)
    assert events[0]["reason"] == "directory does not exist"
    assert events[0]["log_level"] == "warning"


def test_empty_env_dir_warns_with_no_migrations_reason(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    empty = tmp_path / "empty-migrations"
    empty.mkdir()
    monkeypatch.setenv("OPENSQUILLA_MIGRATIONS_DIR", str(empty))
    with structlog.testing.capture_logs() as captured:
        resolved = _resolve_migrations_dir()
    assert resolved != empty
    events = _env_ignored_events(captured)
    assert len(events) == 1
    assert events[0]["path"] == str(empty)
    assert events[0]["reason"] == "no V*.py migration files found"


def test_usable_env_dir_wins_without_warning(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pinned = tmp_path / "pinned-migrations"
    pinned.mkdir()
    (pinned / "V001__synthetic.py").write_text("steps = []\n")
    monkeypatch.setenv("OPENSQUILLA_MIGRATIONS_DIR", str(pinned))
    with structlog.testing.capture_logs() as captured:
        resolved = _resolve_migrations_dir()
    assert resolved == pinned
    assert _env_ignored_events(captured) == []
