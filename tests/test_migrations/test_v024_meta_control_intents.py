"""Regression coverage for the additive durable MetaSkill-control ledger."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from yoyo import get_backend, read_migrations

from opensquilla.persistence.migrator import apply_pending

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"
V024_ID = "V024__meta_control_intents"


def test_v024_applies_constraints_indexes_and_rolls_back(tmp_path: Path) -> None:
    db_path = tmp_path / "sessions.db"
    applied = apply_pending(str(db_path), MIGRATIONS_DIR)
    assert V024_ID in applied

    connection = sqlite3.connect(db_path)
    try:
        columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(meta_control_intents)")
        }
        assert {
            "intent_id",
            "session_key",
            "control_kind",
            "correlation_id",
            "meta_skill_name",
            "replay_run_id",
            "replay_mode",
            "status",
            "accepted_request_fingerprint",
            "accepted_message_id",
            "accepted_task_id",
        } <= columns
        indexes = {
            str(row[1]): bool(row[2])
            for row in connection.execute("PRAGMA index_list(meta_control_intents)")
        }
        assert indexes["uq_meta_control_intents_correlation"] is True
        assert indexes["idx_meta_control_intents_session_status"] is False

        row = (
            "intent-1",
            "agent:main:test",
            "manual",
            "request:req-1",
            "meta-paper-write",
            "staged",
            1,
            1,
        )
        connection.execute(
            """
            INSERT INTO meta_control_intents (
                intent_id, session_key, control_kind, correlation_id,
                meta_skill_name, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            row,
        )
        connection.commit()
        try:
            connection.execute(
                """
                INSERT INTO meta_control_intents (
                    intent_id, session_key, control_kind, correlation_id,
                    meta_skill_name, status, created_at, updated_at
                ) VALUES ('intent-2', 'agent:main:test', 'manual',
                          'request:req-1', 'other', 'staged', 2, 2)
                """
            )
        except sqlite3.IntegrityError:
            pass
        else:  # pragma: no cover - explicit invariant failure
            raise AssertionError("duplicate control correlation was accepted")
    finally:
        connection.close()

    backend = get_backend(f"sqlite:///{db_path}")
    migrations = read_migrations(str(MIGRATIONS_DIR)).filter(
        lambda migration: migration.id == V024_ID
    )
    with backend.lock():
        backend.rollback_migrations(migrations)

    connection = sqlite3.connect(db_path)
    try:
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='meta_control_intents'"
        ).fetchone()
        assert exists is None
    finally:
        connection.close()
