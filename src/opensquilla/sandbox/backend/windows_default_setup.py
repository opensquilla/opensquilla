"""Setup state for the Windows default sandbox."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SETUP_VERSION = 1


@dataclass(frozen=True)
class WindowsDefaultSetupMarker:
    setup_version: int

    def to_json(self) -> dict[str, object]:
        return {"setupVersion": self.setup_version}


def default_setup_marker_path(home: Path | None = None) -> Path:
    root = home if home is not None else Path.home()
    return root / ".opensquilla" / "sandbox" / "setup_marker.json"


def write_setup_marker(path: Path, *, setup_version: int = SETUP_VERSION) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"setupVersion": setup_version}, sort_keys=True),
        encoding="utf-8",
    )


def read_setup_marker(path: Path) -> WindowsDefaultSetupMarker | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    version = raw.get("setupVersion")
    if not isinstance(version, int):
        return None
    return WindowsDefaultSetupMarker(setup_version=version)


def setup_marker_is_current(path: Path) -> bool:
    marker = read_setup_marker(path)
    return marker is not None and marker.setup_version == SETUP_VERSION


def setup_payload(path: Path) -> dict[str, Any]:
    return {
        "setupVersion": SETUP_VERSION,
        "markerPath": str(path),
        "sandboxStateRoot": str(path.parent),
        "sandboxSecretsRoot": str(path.parent.parent / "sandbox-secrets"),
        "sandboxBinRoot": str(path.parent.parent / "sandbox-bin"),
    }


__all__ = [
    "SETUP_VERSION",
    "WindowsDefaultSetupMarker",
    "default_setup_marker_path",
    "read_setup_marker",
    "setup_marker_is_current",
    "setup_payload",
    "write_setup_marker",
]
