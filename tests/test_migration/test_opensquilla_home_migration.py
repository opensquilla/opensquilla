"""OpenSquilla self-migration: legacy home import into the current home.

All homes here are synthetic (dummy values only) and built in tmp_path; the
config content reuses the golden cli-0.1 fixture so the import exercises a
real released-era config shape.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
import tomllib
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import tomli_w

from opensquilla.migration import orchestrator
from opensquilla.migration.opensquilla_home import (
    IMPORT_MARKER_FILENAME,
    OpenSquillaHomeMigrator,
    OpenSquillaMigrationOptions,
    detect_legacy_cli_home,
    enumerate_portable_homes,
    is_valid_opensquilla_home,
)

FIXTURE_CONFIG = Path(__file__).parent / "fixtures" / "homes" / "cli-0.1" / "config.toml"

DUMMY_INLINE_KEY = "dummy-inline-key-123"

REPORT_KEYS = {
    "source",
    "source_kind",
    "target",
    "output_dir",
    "apply",
    "items",
    "candidates",
    "config_transforms",
    "secret_relocations",
    "paused_jobs",
    "preflight",
    "notes",
}

# Base scheduler_jobs DDL as scheduler/persistence.py creates it (the
# ``enabled`` column arrived later via a conditional column add).
_SCHEDULER_JOBS_DDL = """
CREATE TABLE IF NOT EXISTS scheduler_jobs (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    cron_expr TEXT NOT NULL,
    handler_key TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_run_at TEXT,
    next_run_at TEXT,
    run_count INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    max_retries INTEGER NOT NULL DEFAULT 3,
    jitter_seconds REAL NOT NULL DEFAULT 0.0
)
"""


def _write_config(home: Path) -> None:
    payload = tomllib.loads(FIXTURE_CONFIG.read_text(encoding="utf-8"))
    payload["llm"]["api_key"] = DUMMY_INLINE_KEY
    (home / "config.toml").write_text(tomli_w.dumps(payload), encoding="utf-8")


def _write_sessions_db(home: Path, applied_ids: tuple[str, ...]) -> None:
    db_path = home / "state" / "sessions.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            "CREATE TABLE _yoyo_migration ("
            "migration_hash TEXT PRIMARY KEY, "
            "migration_id TEXT, "
            "applied_at_utc TIMESTAMP)"
        )
        for index, migration_id in enumerate(applied_ids):
            connection.execute(
                "INSERT INTO _yoyo_migration VALUES (?, ?, ?)",
                (f"dummy-hash-{index}", migration_id, "2026-01-01 00:00:00"),
            )
        connection.commit()
    finally:
        connection.close()


def _write_scheduler_db(home: Path, *, with_enabled_column: bool) -> None:
    db_path = home / "state" / "scheduler.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(_SCHEDULER_JOBS_DDL)
        if with_enabled_column:
            connection.execute(
                "ALTER TABLE scheduler_jobs ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1"
            )
        connection.execute(
            "INSERT INTO scheduler_jobs "
            "(id, name, cron_expr, handler_key, payload, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "job-1",
                "dummy daily job",
                "0 9 * * *",
                "agent_turn",
                "{}",
                "pending",
                "2026-01-01 00:00:00",
                "2026-01-01 00:00:00",
            ),
        )
        connection.commit()
    finally:
        connection.close()


def _build_source_home(
    root: Path,
    *,
    with_enabled_column: bool = True,
    applied_ids: tuple[str, ...] = ("V001__initial_schema",),
) -> Path:
    home = root / "legacy-home"
    (home / "workspace" / "memory").mkdir(parents=True)
    (home / "workspace" / "MEMORY.md").write_text(
        "# Memory index\n\n- dummy entry\n", encoding="utf-8"
    )
    (home / "workspace" / "memory" / "2026-01-01.md").write_text(
        "- dated dummy note\n", encoding="utf-8"
    )
    (home / "skills" / "dummy-skill").mkdir(parents=True)
    (home / "skills" / "dummy-skill" / "SKILL.md").write_text(
        "---\nname: dummy-skill\ndescription: a dummy skill\n---\n\nBody.\n",
        encoding="utf-8",
    )
    (home / ".env").write_text("OPENROUTER_API_KEY=dummy\n", encoding="utf-8")
    (home / "profiles" / "dummy-profile").mkdir(parents=True)
    (home / "profiles" / "dummy-profile" / "config.toml").write_text(
        "port = 18791\n", encoding="utf-8"
    )
    _write_config(home)
    _write_sessions_db(home, applied_ids)
    _write_scheduler_db(home, with_enabled_column=with_enabled_column)
    return home


def _run(
    source: Path, target: Path, *, apply: bool = False, overwrite: bool = False
) -> dict[str, Any]:
    options = OpenSquillaMigrationOptions(
        source=source, target=target, apply=apply, overwrite=overwrite
    )
    return OpenSquillaHomeMigrator(options).migrate()


def _errors(report: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in report["items"] if item["status"] == "error"]


def _scheduler_enabled_values(db_path: Path) -> list[int]:
    connection = sqlite3.connect(db_path)
    try:
        return [row[0] for row in connection.execute("SELECT enabled FROM scheduler_jobs")]
    finally:
        connection.close()


# ---------------------------------------------------------------------------
# 1. Dry-run
# ---------------------------------------------------------------------------


def test_dry_run_produces_full_report_and_writes_nothing(tmp_path: Path) -> None:
    source = _build_source_home(tmp_path)
    target = tmp_path / "target-home"

    report = _run(source, target, apply=False)

    assert set(report) == REPORT_KEYS
    assert report["apply"] is False
    assert report["output_dir"] == ""
    assert not _errors(report)

    # Planned home entries, with profiles/ excluded.
    planned = {
        Path(item["source"]).name
        for item in report["items"]
        if item["kind"] == "home-entry" and item["status"] == "planned"
    }
    assert {"workspace", "skills", "state", "config.toml", ".env"} <= planned
    skipped = [
        item
        for item in report["items"]
        if item["kind"] == "home-entry" and item["status"] == "skipped"
    ]
    assert any(Path(item["source"]).name == "profiles" for item in skipped)

    # Paused-jobs preview read from the source scheduler.db.
    assert report["paused_jobs"] == [
        {"id": "job-1", "name": "dummy daily job", "cron_expr": "0 9 * * *"}
    ]

    # Transform and secret plans are present, redacted.
    assert any("port: 18790 -> 18791" in entry for entry in report["config_transforms"])
    assert {"config_path": "llm.api_key", "env_key": "OPENROUTER_API_KEY", "moved": True} in (
        report["secret_relocations"]
    )
    assert DUMMY_INLINE_KEY not in json.dumps(report)

    # Nothing was written anywhere: no target, no output dir, no staging,
    # and the source home is untouched.
    assert not target.exists()
    assert not list(tmp_path.glob(".opensquilla-import-*"))
    assert not (source / IMPORT_MARKER_FILENAME).exists()
    source_config = tomllib.loads((source / "config.toml").read_text(encoding="utf-8"))
    assert source_config["port"] == 18790
    assert source_config["llm"]["api_key"] == DUMMY_INLINE_KEY


# ---------------------------------------------------------------------------
# 2. Apply
# ---------------------------------------------------------------------------


def test_apply_imports_home_with_transforms(tmp_path: Path) -> None:
    source = _build_source_home(tmp_path, with_enabled_column=True)
    target = tmp_path / "target-home"

    report = _run(source, target, apply=True)

    assert not _errors(report)
    assert report["apply"] is True

    # Entries landed; profiles/ excluded; runtime pid locks excluded.
    assert (target / "workspace" / "MEMORY.md").is_file()
    assert (target / "workspace" / "memory" / "2026-01-01.md").is_file()
    assert (target / "skills" / "dummy-skill" / "SKILL.md").is_file()
    assert (target / "state" / "sessions.db").is_file()
    assert not (target / "profiles").exists()
    assert not (target / "state" / "gateway.pid").exists()

    # Config transforms: absolute path pins dropped, port coerced, secret
    # relocated to .env with the env pointer left behind.
    config = tomllib.loads((target / "config.toml").read_text(encoding="utf-8"))
    assert "state_dir" not in config
    assert "workspace_dir" not in config
    assert config["port"] == 18791
    assert "api_key" not in config["llm"]
    assert config["llm"]["api_key_env"] == "OPENROUTER_API_KEY"

    env_text = (target / ".env").read_text(encoding="utf-8")
    assert f"OPENROUTER_API_KEY={DUMMY_INLINE_KEY}" in env_text
    assert env_text.count("OPENROUTER_API_KEY=") == 1

    # Imported scheduler jobs all arrive paused.
    assert _scheduler_enabled_values(target / "state" / "scheduler.db") == [0]
    assert report["paused_jobs"] == [
        {"id": "job-1", "name": "dummy daily job", "cron_expr": "0 9 * * *"}
    ]

    # Pristine db snapshot exists under the report output dir.
    output_dir = Path(report["output_dir"])
    assert (output_dir / "db-snapshots" / "scheduler.db").is_file()
    assert (output_dir / "report.json").is_file()
    assert (output_dir / "summary.md").is_file()

    # No staging dir left behind.
    assert not list(tmp_path.glob(".opensquilla-import-*"))

    # Source home unchanged except the completion marker.
    marker = json.loads((source / IMPORT_MARKER_FILENAME).read_text(encoding="utf-8"))
    assert marker["target"] == str(target)
    source_config = tomllib.loads((source / "config.toml").read_text(encoding="utf-8"))
    assert source_config["port"] == 18790
    assert source_config["llm"]["api_key"] == DUMMY_INLINE_KEY
    assert _scheduler_enabled_values(source / "state" / "scheduler.db") == [1]

    # The report never carries the secret value.
    assert DUMMY_INLINE_KEY not in json.dumps(report)


def test_apply_pauses_jobs_when_enabled_column_is_absent(tmp_path: Path) -> None:
    source = _build_source_home(tmp_path, with_enabled_column=False)
    target = tmp_path / "target-home"

    report = _run(source, target, apply=True)

    assert not _errors(report)
    # The column was added pre-seeded at 0, so JobStore's later conditional
    # add (default 1) never fires and imported jobs arrive paused.
    assert _scheduler_enabled_values(target / "state" / "scheduler.db") == [0]
    assert report["paused_jobs"] == [
        {"id": "job-1", "name": "dummy daily job", "cron_expr": "0 9 * * *"}
    ]


# ---------------------------------------------------------------------------
# 3. Non-empty target gate
# ---------------------------------------------------------------------------


def test_non_empty_target_refused_without_overwrite(tmp_path: Path) -> None:
    source = _build_source_home(tmp_path)
    target = tmp_path / "target-home"
    (target / "state").mkdir(parents=True)
    (target / "state" / "sessions.db").write_bytes(b"dummy existing db")

    report = _run(source, target, apply=True)

    errors = _errors(report)
    assert errors
    assert any("--overwrite" in item["reason"] for item in errors)
    # Nothing was imported.
    assert not (target / "workspace").exists()
    assert (target / "state" / "sessions.db").read_bytes() == b"dummy existing db"
    assert not (source / IMPORT_MARKER_FILENAME).exists()


def test_overwrite_takes_timestamped_backups(tmp_path: Path) -> None:
    source = _build_source_home(tmp_path)
    target = tmp_path / "target-home"
    (target / "state").mkdir(parents=True)
    (target / "state" / "sessions.db").write_bytes(b"dummy existing db")

    report = _run(source, target, apply=True, overwrite=True)

    assert not _errors(report)
    backups = list(target.glob("state.backup.*"))
    assert len(backups) == 1
    assert (backups[0] / "sessions.db").read_bytes() == b"dummy existing db"
    # The imported store replaced the old one.
    assert (target / "state" / "sessions.db").read_bytes() != b"dummy existing db"


# ---------------------------------------------------------------------------
# 4.-6. Pre-flight refusals
# ---------------------------------------------------------------------------


def test_live_source_gateway_refused(tmp_path: Path) -> None:
    source = _build_source_home(tmp_path)
    (source / "state" / "gateway.pid").write_text(
        json.dumps({"pid": os.getpid(), "start_ts": "2026-01-01T00:00:00+00:00"}),
        encoding="utf-8",
    )
    target = tmp_path / "target-home"

    report = _run(source, target, apply=True)

    assert report["preflight"]["source_gateway_running"] is True
    errors = _errors(report)
    assert any("gateway is running on the source home" in item["reason"] for item in errors)
    assert not target.exists()


def test_schema_ahead_source_refused(tmp_path: Path) -> None:
    source = _build_source_home(
        tmp_path, applied_ids=("V001__initial_schema", "V999__future_thing")
    )
    target = tmp_path / "target-home"

    report = _run(source, target, apply=True)

    assert report["preflight"]["schema_ahead"] is True
    errors = _errors(report)
    assert any("newer OpenSquilla" in item["reason"] for item in errors)
    assert any("V999__future_thing" in item["reason"] for item in errors)
    assert not target.exists()


def test_insufficient_disk_space_refused(tmp_path: Path, monkeypatch) -> None:
    source = _build_source_home(tmp_path)
    target = tmp_path / "target-home"
    monkeypatch.setattr(
        "shutil.disk_usage",
        lambda _path: SimpleNamespace(total=1000, used=990, free=10),
    )

    report = _run(source, target, apply=True)

    assert report["preflight"]["disk_free_bytes"] == 10
    assert report["preflight"]["disk_required_bytes"] > 10
    errors = _errors(report)
    assert any("not enough free disk space" in item["reason"] for item in errors)
    assert not target.exists()


# ---------------------------------------------------------------------------
# 7. CLI-home detection guard
# ---------------------------------------------------------------------------


def test_detect_legacy_cli_home_guard(tmp_path: Path, monkeypatch) -> None:
    fake_home = tmp_path / "userhome"
    legacy = fake_home / ".opensquilla"
    legacy.mkdir(parents=True)
    (legacy / "config.toml").write_text("port = 18790\n", encoding="utf-8")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

    # The active home IS ~/.opensquilla: never offered as a source.
    assert detect_legacy_cli_home(legacy) is None
    # Symlink-equivalent spelling of the same home is also rejected.
    assert detect_legacy_cli_home(fake_home / ".opensquilla" / ".." / ".opensquilla") is None
    # A different target (desktop spawn, relocated state dir): offered.
    assert detect_legacy_cli_home(tmp_path / "electron-home") == legacy


def test_is_valid_opensquilla_home_shapes(tmp_path: Path) -> None:
    assert not is_valid_opensquilla_home(tmp_path / "missing")
    empty = tmp_path / "empty"
    empty.mkdir()
    assert not is_valid_opensquilla_home(empty)
    with_state = tmp_path / "with-state"
    (with_state / "state").mkdir(parents=True)
    assert is_valid_opensquilla_home(with_state)
    with_workspace = tmp_path / "with-workspace"
    (with_workspace / "workspace").mkdir(parents=True)
    assert is_valid_opensquilla_home(with_workspace)


# ---------------------------------------------------------------------------
# 8. Portable enumeration
# ---------------------------------------------------------------------------


def test_enumerate_portable_homes_orders_and_era_hints(tmp_path: Path) -> None:
    base = tmp_path / "appdata"
    portable = base / "OpenSquilla" / "portable"
    older = portable / "dummy-release-a"
    newer = portable / "dummy-release-b"
    older.mkdir(parents=True)
    newer.mkdir(parents=True)
    (older / "config.toml").write_text("port = 18790\n", encoding="utf-8")
    (older / "install-receipt.json").write_text(
        json.dumps({"version": "0.4.1"}), encoding="utf-8"
    )
    (newer / "config.toml").write_text("port = 18790\n", encoding="utf-8")
    (newer / "state").mkdir()
    (newer / "state" / "update_check.json").write_text("{}", encoding="utf-8")

    now = time.time()
    os.utime(older / "config.toml", (now - 1000, now - 1000))
    os.utime(newer / "config.toml", (now, now))

    candidates = enumerate_portable_homes([base])

    assert [candidate.path for candidate in candidates] == [newer, older]
    assert candidates[0].era_hint == "0.5.0rc2+"
    assert candidates[1].era_hint == "0.4.1"
    assert candidates[0].last_used > candidates[1].last_used
    assert all(candidate.size_bytes > 0 for candidate in candidates)


# ---------------------------------------------------------------------------
# 9. WAL sidecars
# ---------------------------------------------------------------------------


def test_wal_sidecar_travels_with_the_store(tmp_path: Path) -> None:
    source = _build_source_home(tmp_path)
    (source / "state" / "sessions.db-wal").write_bytes(b"")
    target = tmp_path / "target-home"

    report = _run(source, target, apply=True)

    assert not _errors(report)
    assert (target / "state" / "sessions.db-wal").is_file()


# ---------------------------------------------------------------------------
# Orchestrator wiring
# ---------------------------------------------------------------------------


def test_orchestrator_rejects_non_default_item_options_for_opensquilla() -> None:
    options = orchestrator.MigrationBatchOptions(preset="user-data")
    try:
        orchestrator.validate_batch_options(("opensquilla",), options)
    except orchestrator.MigrationOptionError as exc:
        assert "does not take preset/include/exclude" in str(exc)
    else:
        raise AssertionError("non-default preset must be rejected for opensquilla")


def test_orchestrator_accepts_wizard_defaults_for_opensquilla() -> None:
    options = orchestrator.MigrationBatchOptions(
        preset="full", skill_conflict="skip", persona_conflict="use-opensquilla"
    )
    orchestrator.validate_batch_options(("opensquilla",), options)


def test_orchestrator_runs_opensquilla_source(tmp_path: Path, monkeypatch) -> None:
    source = _build_source_home(tmp_path)
    target = tmp_path / "target-home"
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(target))

    report = orchestrator.run_one_migration(
        "opensquilla", source, orchestrator.MigrationBatchOptions(apply=False)
    )

    assert report["source_kind"] == "cli-home"
    assert report["target"] == str(target)
    assert not any(item["status"] == "error" for item in report["items"])
