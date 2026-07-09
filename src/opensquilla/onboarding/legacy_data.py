"""Nullable legacy-data advisory block shared by the onboarding surfaces.

Both the ``onboarding.status`` RPC payload and the CLI
``opensquilla onboard status --json`` payload (a pinned superset of the RPC
shape) carry the same ``legacyData`` block, so it is built in exactly one
place. Detection reuses the migration module's read-only path scan and is
safe under a running gateway; the import itself stays at the CLI layer
(``opensquilla migrate opensquilla``), which requires a quiesced gateway.
"""

from __future__ import annotations

import importlib
from typing import Any


def legacy_data_payload() -> dict[str, Any] | None:
    """Return ``{"path", "kind", "command"}`` for a detected legacy home, else None."""
    legacy_detect = importlib.import_module("opensquilla.migration.legacy_detect")

    candidate = legacy_detect.detect_legacy_home()
    if candidate is None:
        return None
    return {
        "path": str(candidate.path),
        "kind": candidate.kind,
        "command": legacy_detect.suggested_migrate_command(candidate),
    }
