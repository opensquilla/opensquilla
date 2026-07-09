"""Boot-time advisory for importable legacy OpenSquilla homes.

``_warn_legacy_home_detected`` must warn exactly once on the fresh-home +
candidate combination and stay silent (without even running detection) on an
established home. Structured warnings are captured by monkeypatching the boot
module's ``log.warning``, the same technique as the workspace/state mismatch
test in ``test_router_boot.py``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from opensquilla.gateway.boot import _warn_legacy_home_detected
from opensquilla.gateway.config import GatewayConfig
from opensquilla.migration import legacy_detect
from opensquilla.migration.legacy_detect import LegacyHomeCandidate


def _capture_warnings(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "opensquilla.gateway.boot.log.warning",
        lambda event, **kwargs: warnings.append({"event": event, **kwargs}),
    )
    return warnings


def _config(tmp_path: Path) -> GatewayConfig:
    return GatewayConfig(
        state_dir=str(tmp_path / "home" / "state"),
        config_path=str(tmp_path / "home" / "config.toml"),
    )


def test_fresh_home_with_candidate_warns_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    warnings = _capture_warnings(monkeypatch)
    legacy = tmp_path / "legacy-home"
    seen_targets: list[Path | None] = []

    def _detect(target: Path | None = None) -> LegacyHomeCandidate:
        seen_targets.append(target)
        return LegacyHomeCandidate(path=legacy, kind="cli-home")

    monkeypatch.setattr(legacy_detect, "detect_legacy_home", _detect)

    _warn_legacy_home_detected(_config(tmp_path))

    assert len(warnings) == 1
    assert warnings[0] == {
        "event": "build_services.legacy_home_detected",
        "legacy_home": str(legacy),
        "kind": "cli-home",
        "migrate_command": (
            f"opensquilla migrate opensquilla --kind cli-home --source {legacy}"
        ),
    }
    # Detection ran once, against the home the gateway actually booted from.
    assert seen_targets == [(tmp_path / "home").resolve()]


def test_established_home_is_silent_and_skips_detection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    warnings = _capture_warnings(monkeypatch)
    state_dir = tmp_path / "home" / "state"
    state_dir.mkdir(parents=True)
    (state_dir / "sessions.db").write_bytes(b"")
    calls: list[Path | None] = []
    monkeypatch.setattr(
        legacy_detect,
        "detect_legacy_home",
        lambda target=None: calls.append(target),
    )

    _warn_legacy_home_detected(_config(tmp_path))

    assert warnings == []
    assert calls == []


def test_fresh_home_without_candidate_is_silent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    warnings = _capture_warnings(monkeypatch)
    monkeypatch.setattr(legacy_detect, "detect_legacy_home", lambda target=None: None)

    _warn_legacy_home_detected(_config(tmp_path))

    assert warnings == []
