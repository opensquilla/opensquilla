from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from opensquilla.observability import update_check


@pytest.fixture(autouse=True)
def _reset_module_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    # The module memoizes the last result in a global; clear it between tests.
    monkeypatch.setattr(update_check, "_CACHED_INFO", None)


def _enable(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        update_check.UPDATE_CHECK_DISABLED_ENV,
        update_check.TELEMETRY_DISABLED_ENV,
        "GITHUB_ACTIONS",
        "PYTEST_CURRENT_TEST",
        update_check.TELEMETRY_TESTING_ENV,
    ):
        monkeypatch.delenv(name, raising=False)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _fake_fetch(
    tag: str | None,
    url: str | None = "https://example.test/r",
    error: str | None = None,
):
    calls: list[str] = []

    def fetch(endpoint: str, current_version: str, *, timeout: float):
        calls.append(endpoint)
        return tag, url, error

    fetch.calls = calls  # type: ignore[attr-defined]
    return fetch


@pytest.mark.parametrize(
    ("latest", "current", "expected"),
    [
        ("0.5.0", "0.4.1", True),
        ("0.4.1", "0.4.1", False),
        ("0.4.0", "0.4.1", False),
        ("v0.5.0", "0.4.1", True),  # leading v tolerated
        ("0.4.1", "0.4.1rc1", True),  # release supersedes its own pre-release
        # Pre-release ordinals are intentionally NOT compared: releases/latest
        # never returns a pre-release, so two same-core pre-releases are "equal".
        ("0.4.1rc2", "0.4.1rc1", False),
        ("0.5.0", "0.0.0+unknown", False),  # dev/source checkout is never nagged
        ("0.5.0", None, False),
    ],
)
def test_is_newer(latest: str, current: str | None, expected: bool) -> None:
    assert update_check._is_newer(latest, current) is expected


def test_refresh_detects_and_persists_update(tmp_path: Path, monkeypatch) -> None:
    _enable(monkeypatch)
    fetch = _fake_fetch("0.5.0", "https://example.test/release")
    monkeypatch.setattr(update_check, "_fetch_latest_release", fetch)
    state_path = tmp_path / "update_check.json"

    info = update_check.refresh_update_check(state_path=state_path, version="0.4.1")

    assert info.update_available is True
    assert info.latest_version == "0.5.0"
    assert info.release_url == "https://example.test/release"
    assert info.to_public_dict()["available"] is True
    state = _load(state_path)
    assert state["latest_version"] == "0.5.0"
    assert isinstance(state["checked_ts"], int)


def test_refresh_reports_no_update(tmp_path: Path, monkeypatch) -> None:
    _enable(monkeypatch)
    monkeypatch.setattr(update_check, "_fetch_latest_release", _fake_fetch("0.4.1"))
    state_path = tmp_path / "update_check.json"

    info = update_check.refresh_update_check(state_path=state_path, version="0.4.1")

    assert info.latest_version == "0.4.1"
    assert info.update_available is False


def test_refresh_uses_cache_within_ttl(tmp_path: Path, monkeypatch) -> None:
    _enable(monkeypatch)
    fetch = _fake_fetch("0.5.0")
    monkeypatch.setattr(update_check, "_fetch_latest_release", fetch)
    state_path = tmp_path / "update_check.json"

    first = update_check.refresh_update_check(state_path=state_path, version="0.4.1")
    # Drop the in-memory cache so the TTL path is exercised via the state file.
    monkeypatch.setattr(update_check, "_CACHED_INFO", None)
    second = update_check.refresh_update_check(state_path=state_path, version="0.4.1")

    assert first.update_available is True
    assert second.update_available is True
    assert second.from_cache is True
    assert len(fetch.calls) == 1  # second call served from cache, no network


def test_force_bypasses_ttl(tmp_path: Path, monkeypatch) -> None:
    _enable(monkeypatch)
    fetch = _fake_fetch("0.5.0")
    monkeypatch.setattr(update_check, "_fetch_latest_release", fetch)
    state_path = tmp_path / "update_check.json"

    update_check.refresh_update_check(state_path=state_path, version="0.4.1")
    update_check.refresh_update_check(state_path=state_path, version="0.4.1", force=True)

    assert len(fetch.calls) == 2


def test_disabled_env_skips_network(tmp_path: Path, monkeypatch) -> None:
    _enable(monkeypatch)
    monkeypatch.setenv(update_check.UPDATE_CHECK_DISABLED_ENV, "1")
    fetch = _fake_fetch("0.5.0")
    monkeypatch.setattr(update_check, "_fetch_latest_release", fetch)
    state_path = tmp_path / "update_check.json"

    info = update_check.refresh_update_check(state_path=state_path, version="0.4.1")

    assert info.disabled is True
    assert info.update_available is False
    assert fetch.calls == []


def test_disabled_env_skips_forced_network_check(tmp_path: Path, monkeypatch) -> None:
    _enable(monkeypatch)
    monkeypatch.setenv(update_check.UPDATE_CHECK_DISABLED_ENV, "1")
    fetch = _fake_fetch("0.5.0")
    monkeypatch.setattr(update_check, "_fetch_latest_release", fetch)

    info = update_check.refresh_update_check(
        state_path=tmp_path / "update_check.json",
        version="0.4.1",
        force=True,
    )

    assert info.disabled is True
    assert info.update_available is False
    assert fetch.calls == []


def test_telemetry_disable_also_silences_update_check(tmp_path: Path, monkeypatch) -> None:
    _enable(monkeypatch)
    monkeypatch.setenv(update_check.TELEMETRY_DISABLED_ENV, "1")
    fetch = _fake_fetch("0.5.0")
    monkeypatch.setattr(update_check, "_fetch_latest_release", fetch)

    info = update_check.refresh_update_check(
        state_path=tmp_path / "update_check.json", version="0.4.1"
    )

    assert info.disabled is True
    assert fetch.calls == []


def test_get_cached_honors_disabled_env_after_prior_check(tmp_path: Path, monkeypatch) -> None:
    _enable(monkeypatch)
    monkeypatch.setattr(update_check, "_fetch_latest_release", _fake_fetch("0.5.0"))
    state_path = tmp_path / "update_check.json"
    update_check.refresh_update_check(state_path=state_path, version="0.4.1")

    monkeypatch.setenv(update_check.UPDATE_CHECK_DISABLED_ENV, "1")
    info = update_check.get_cached_update_info(state_path=state_path, version="0.4.1")

    assert info is None


def test_get_cached_recomputes_against_current_version(tmp_path: Path, monkeypatch) -> None:
    _enable(monkeypatch)
    monkeypatch.setattr(update_check, "_fetch_latest_release", _fake_fetch("0.5.0"))
    state_path = tmp_path / "update_check.json"
    update_check.refresh_update_check(state_path=state_path, version="0.4.1")

    # The just-upgraded process (now 0.5.0) should no longer see an update.
    info = update_check.get_cached_update_info(state_path=state_path, version="0.5.0")
    assert info is not None
    assert info.update_available is False

    # A still-older process keeps seeing it.
    stale = update_check.get_cached_update_info(state_path=state_path, version="0.4.1")
    assert stale is not None
    assert stale.update_available is True


def test_get_cached_returns_none_before_first_check(tmp_path: Path, monkeypatch) -> None:
    _enable(monkeypatch)
    info = update_check.get_cached_update_info(
        state_path=tmp_path / "update_check.json", version="0.4.1"
    )
    assert info is None


def test_fetch_failure_keeps_prior_cache(tmp_path: Path, monkeypatch) -> None:
    _enable(monkeypatch)
    state_path = tmp_path / "update_check.json"
    monkeypatch.setattr(update_check, "_fetch_latest_release", _fake_fetch("0.5.0"))
    update_check.refresh_update_check(state_path=state_path, version="0.4.1")

    # A later check fails (offline); the previously-known latest must survive.
    monkeypatch.setattr(
        update_check, "_fetch_latest_release", _fake_fetch(None, None, "offline")
    )
    monkeypatch.setattr(update_check, "_CACHED_INFO", None)
    info = update_check.refresh_update_check(
        state_path=state_path, version="0.4.1", force=True
    )

    assert info.latest_version == "0.5.0"
    assert info.update_available is True
    assert info.error == "offline"
