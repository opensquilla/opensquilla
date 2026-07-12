"""Migration startup diagnostics used by Desktop recovery failure reports."""

from __future__ import annotations

import logging
from pathlib import Path

from opensquilla.persistence.migrator import apply_pending

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


def test_fresh_database_migration_reports_each_blocking_phase(
    tmp_path: Path,
    caplog,
) -> None:
    caplog.set_level(logging.DEBUG, logger="opensquilla.persistence.migrator")

    applied = apply_pending(str(tmp_path / "sessions.db"), MIGRATIONS_DIR)

    assert applied
    messages = [record.getMessage() for record in caplog.records]
    expected = [
        "migrator.backend_open_started",
        "migrator.backend_open_ready",
        "migrator.discovery_started",
        "migrator.discovery_ready",
        "migrator.lock_wait_started",
        "migrator.lock_acquired",
        "migrator.plan_ready",
        "migrator.apply_started",
        "migrator.apply_ready",
    ]
    positions = [messages.index(message) for message in expected]
    assert positions == sorted(positions)
