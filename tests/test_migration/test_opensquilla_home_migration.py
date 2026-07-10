"""OpenSquilla self-migration: legacy home import into the current home.

All homes here are synthetic (dummy values only) and built in tmp_path; the
config content reuses the golden cli-0.1 fixture so the import exercises a
real released-era config shape.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import time
import tomllib
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import tomli_w

import opensquilla.gateway.config_migration as config_migration_module
import opensquilla.migration.opensquilla_home as migration_module
from opensquilla.artifacts import ArtifactStore
from opensquilla.attachment_refs import (
    make_attachment_ref,
    read_attachment_ref_bytes,
    write_transcript_material,
)
from opensquilla.migration import orchestrator
from opensquilla.migration.opensquilla_home import (
    IMPORT_MARKER_FILENAME,
    OpenSquillaHomeMigrator,
    OpenSquillaMigrationOptions,
    detect_legacy_cli_home,
    enumerate_portable_homes,
    is_valid_opensquilla_home,
)
from opensquilla.persistence.migrator import apply_pending
from opensquilla.session.manager import SessionManager
from opensquilla.session.models import TranscriptEntry
from opensquilla.session.storage import SessionStorage

FIXTURE_CONFIG = Path(__file__).parent / "fixtures" / "homes" / "cli-0.1" / "config.toml"
MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"

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


def _file_bytes(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


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


def test_direct_migrator_rejects_config_path_without_writing(tmp_path: Path) -> None:
    source = _build_source_home(tmp_path)
    target = tmp_path / "target-home"

    report = OpenSquillaHomeMigrator(
        OpenSquillaMigrationOptions(
            source=source,
            target=target,
            config_path=tmp_path / "unsupported.toml",
            apply=True,
        )
    ).migrate()

    assert any(
        item["kind"] == "options" and "config_path is not supported" in item["reason"]
        for item in _errors(report)
    )
    assert not target.exists()
    assert not (source / IMPORT_MARKER_FILENAME).exists()


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


def test_imported_config_and_env_are_owner_only_even_without_secret_rewrite(
    tmp_path: Path,
) -> None:
    source = _build_source_home(tmp_path)
    payload = tomllib.loads((source / "config.toml").read_text(encoding="utf-8"))
    payload["llm"].pop("api_key", None)
    payload["llm"]["api_key_env"] = "OPENROUTER_API_KEY"
    (source / "config.toml").write_text(tomli_w.dumps(payload), encoding="utf-8")
    os.chmod(source / "config.toml", 0o644)
    os.chmod(source / ".env", 0o644)
    target = tmp_path / "target-home"

    report = _run(source, target, apply=True)

    assert not _errors(report)
    assert (target / "config.toml").stat().st_mode & 0o777 == 0o600
    assert (target / ".env").stat().st_mode & 0o777 == 0o600


def test_read_only_source_directories_produce_writable_imported_runtime(
    tmp_path: Path,
) -> None:
    source = _build_source_home(tmp_path)
    os.chmod(source / "state" / "sessions.db", 0o444)
    os.chmod(source / "state", 0o555)
    os.chmod(source / "workspace", 0o555)
    target = tmp_path / "target-home"

    report = _run(source, target, apply=True)

    assert not _errors(report)
    assert (target / "state").stat().st_mode & 0o700 == 0o700
    assert (target / "workspace").stat().st_mode & 0o700 == 0o700
    assert (target / "state" / "sessions.db").stat().st_mode & 0o600 == 0o600
    connection = sqlite3.connect(target / "state" / "sessions.db")
    try:
        connection.execute("CREATE TABLE writable_after_import (id INTEGER)")
        connection.commit()
    finally:
        connection.close()


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
    backups = list(tmp_path.glob("target-home.backup.*"))
    assert len(backups) == 1
    assert (backups[0] / "state" / "sessions.db").read_bytes() == b"dummy existing db"
    # The imported store replaced the old one.
    assert (target / "state" / "sessions.db").read_bytes() != b"dummy existing db"
    persisted = json.loads(
        (Path(report["output_dir"]) / "report.json").read_text(encoding="utf-8")
    )
    returned_backups = [item for item in report["items"] if item["kind"] == "backup"]
    persisted_backups = [item for item in persisted["items"] if item["kind"] == "backup"]
    assert returned_backups
    assert persisted_backups == returned_backups


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


def test_detect_legacy_cli_home_skips_source_already_imported_to_target(
    tmp_path: Path, monkeypatch
) -> None:
    fake_home = tmp_path / "userhome"
    legacy = fake_home / ".opensquilla"
    legacy.mkdir(parents=True)
    (legacy / "config.toml").write_text("port = 18790\n", encoding="utf-8")
    target = tmp_path / "desktop-home"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

    report = _run(legacy, target, apply=True)
    assert not _errors(report)
    assert detect_legacy_cli_home(target) is None
    assert detect_legacy_cli_home(tmp_path / "different-target") == legacy

    # A stale source marker must not hide import after the target was removed
    # by an uninstall/reinstall. Suppression requires the matching target-side
    # receipt produced by the completed transaction.
    shutil.rmtree(target)
    assert detect_legacy_cli_home(target) == legacy


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


def test_sqlite_snapshot_normalizes_empty_wal_sidecar(tmp_path: Path) -> None:
    source = _build_source_home(tmp_path)
    (source / "state" / "sessions.db-wal").write_bytes(b"")
    target = tmp_path / "target-home"

    report = _run(source, target, apply=True)

    assert not _errors(report)
    assert not (target / "state" / "sessions.db-wal").exists()
    connection = sqlite3.connect(target / "state" / "sessions.db")
    try:
        assert connection.execute("PRAGMA quick_check").fetchone() == ("ok",)
    finally:
        connection.close()


def test_dry_run_does_not_create_sidecars_for_checkpointed_wal_store(
    tmp_path: Path,
) -> None:
    source = _build_source_home(tmp_path)
    db_path = source / "state" / "sessions.db"
    connection = sqlite3.connect(db_path)
    try:
        assert connection.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
        connection.commit()
    finally:
        connection.close()
    assert not db_path.with_name("sessions.db-wal").exists()
    assert not db_path.with_name("sessions.db-shm").exists()
    before = _file_bytes(source)

    report = _run(source, tmp_path / "target-home", apply=False)

    assert not _errors(report)
    assert _file_bytes(source) == before


def test_dry_run_reads_committed_wal_without_mutating_source_bundle(
    tmp_path: Path,
) -> None:
    source = _build_source_home(tmp_path)
    db_path = source / "state" / "scheduler.db"
    writer = sqlite3.connect(db_path)
    try:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        writer.execute(
            "INSERT INTO scheduler_jobs "
            "(id, name, cron_expr, handler_key, payload, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "job-wal",
                "committed only in WAL",
                "30 10 * * *",
                "agent_turn",
                "{}",
                "pending",
                "2026-01-02 00:00:00",
                "2026-01-02 00:00:00",
            ),
        )
        writer.commit()
        assert db_path.with_name("scheduler.db-wal").stat().st_size > 0
        before = _file_bytes(source)

        report = _run(source, tmp_path / "target-home", apply=False)

        assert not _errors(report)
        assert {job["id"] for job in report["paused_jobs"]} == {"job-1", "job-wal"}
        assert _file_bytes(source) == before
    finally:
        writer.close()


# ---------------------------------------------------------------------------
# Safety regressions: split roots, fail-closed transforms, atomic publish
# ---------------------------------------------------------------------------


def _point_config_at_split_roots(
    source: Path,
    *,
    state: Path,
    workspace: Path,
    media: Path,
) -> None:
    payload = tomllib.loads((source / "config.toml").read_text(encoding="utf-8"))
    payload["state_dir"] = str(state)
    payload["workspace_dir"] = str(workspace)
    attachments = payload.setdefault("attachments", {})
    attachments["media_root"] = str(media)
    (source / "config.toml").write_text(tomli_w.dumps(payload), encoding="utf-8")


def test_external_configured_roots_are_copied_to_canonical_target_paths(
    tmp_path: Path,
) -> None:
    source = _build_source_home(tmp_path)
    shutil.rmtree(source / "state")
    shutil.rmtree(source / "workspace")
    external_state = tmp_path / "external-state"
    external_workspace = tmp_path / "external-workspace"
    external_media = tmp_path / "external-media"
    external_state.mkdir()
    external_workspace.mkdir()
    external_media.mkdir()
    (external_state / "state-sentinel.bin").write_bytes(b"state-data")
    (external_workspace / "workspace-sentinel.txt").write_text(
        "workspace-data", encoding="utf-8"
    )
    (external_media / "media-sentinel.bin").write_bytes(b"media-data")
    _point_config_at_split_roots(
        source,
        state=external_state,
        workspace=external_workspace,
        media=external_media,
    )
    target = tmp_path / "target-home"

    report = _run(source, target, apply=True)

    assert not _errors(report)
    assert (target / "state" / "state-sentinel.bin").read_bytes() == b"state-data"
    assert (target / "workspace" / "workspace-sentinel.txt").read_text(
        encoding="utf-8"
    ) == "workspace-data"
    assert (target / "media" / "media-sentinel.bin").read_bytes() == b"media-data"
    config = tomllib.loads((target / "config.toml").read_text(encoding="utf-8"))
    assert "state_dir" not in config
    assert "workspace_dir" not in config
    assert "media_root" not in config.get("attachments", {})


def test_windows_absolute_path_pins_are_dropped_on_posix_import(tmp_path: Path) -> None:
    source = _build_source_home(tmp_path)
    (source / "media").mkdir()
    (source / "media" / "sentinel.bin").write_bytes(b"media")
    payload = tomllib.loads((source / "config.toml").read_text(encoding="utf-8"))
    payload["state_dir"] = r"C:\SyntheticOpenSquilla\state"
    payload["workspace_dir"] = r"\\synthetic.invalid\share\workspace"
    payload.setdefault("attachments", {})["media_root"] = (
        r"C:\SyntheticOpenSquilla\media"
    )
    (source / "config.toml").write_text(tomli_w.dumps(payload), encoding="utf-8")
    target = tmp_path / "target-home"

    report = _run(source, target, apply=True)

    assert not _errors(report)
    config = tomllib.loads((target / "config.toml").read_text(encoding="utf-8"))
    assert "state_dir" not in config
    assert "workspace_dir" not in config
    assert "media_root" not in config.get("attachments", {})
    assert (target / "state" / "sessions.db").is_file()
    assert (target / "workspace" / "MEMORY.md").is_file()
    assert (target / "media" / "sentinel.bin").read_bytes() == b"media"


def test_configured_data_root_overlapping_target_is_rejected(tmp_path: Path) -> None:
    source = _build_source_home(tmp_path)
    target = tmp_path / "target-home"
    payload = tomllib.loads((source / "config.toml").read_text(encoding="utf-8"))
    payload["state_dir"] = str(tmp_path)
    (source / "config.toml").write_text(tomli_w.dumps(payload), encoding="utf-8")

    report = _run(source, target, apply=True)

    assert any(
        item["kind"] == "preflight/data-root"
        and "overlaps the target home" in item["reason"]
        for item in _errors(report)
    )
    assert not target.exists()
    assert not list(tmp_path.glob(".opensquilla-import-*"))


def test_external_roots_are_included_in_disk_preflight(tmp_path: Path) -> None:
    source = _build_source_home(tmp_path)
    external_state = tmp_path / "external-state"
    external_workspace = tmp_path / "external-workspace"
    external_media = tmp_path / "external-media"
    for root in (external_state, external_workspace, external_media):
        root.mkdir()
        (root / "payload.bin").write_bytes(b"x" * 4096)
    _point_config_at_split_roots(
        source,
        state=external_state,
        workspace=external_workspace,
        media=external_media,
    )

    report = _run(source, tmp_path / "target-home")

    source_only = migration_module._tree_size_bytes(source)
    assert report["preflight"]["disk_required_bytes"] >= (
        source_only + (3 * 4096) + migration_module._DISK_MARGIN_BYTES
    )


@pytest.mark.parametrize("root_name", ["state", "workspace", "media"])
@pytest.mark.parametrize("invalid_shape", ["missing", "file"])
def test_invalid_configured_data_root_without_canonical_fallback_blocks_apply(
    tmp_path: Path,
    root_name: str,
    invalid_shape: str,
) -> None:
    source = _build_source_home(tmp_path)
    canonical = source / root_name
    if canonical.exists():
        shutil.rmtree(canonical)
    configured = tmp_path / f"invalid-{root_name}"
    if invalid_shape == "file":
        configured.write_text("not a directory", encoding="utf-8")
    payload = tomllib.loads((source / "config.toml").read_text(encoding="utf-8"))
    if root_name == "media":
        payload.setdefault("attachments", {})["media_root"] = str(configured)
    else:
        payload[f"{root_name}_dir"] = str(configured)
    (source / "config.toml").write_text(tomli_w.dumps(payload), encoding="utf-8")
    target = tmp_path / "target-home"

    report = _run(source, target, apply=True)

    data_root_errors = [
        item
        for item in _errors(report)
        if item["kind"] == "preflight/data-root" and item["source"] == str(configured)
    ]
    assert data_root_errors
    assert "refusing to drop its config pin" in data_root_errors[0]["reason"]
    assert not target.exists()
    assert not (source / IMPORT_MARKER_FILENAME).exists()


def test_malformed_config_blocks_apply_without_target_or_marker(tmp_path: Path) -> None:
    source = _build_source_home(tmp_path)
    (source / "config.toml").write_text("[llm\nprovider =", encoding="utf-8")
    target = tmp_path / "target-home"

    report = _run(source, target, apply=True)

    assert any(item["kind"] == "preflight/config" for item in _errors(report))
    assert not target.exists()
    assert not (source / IMPORT_MARKER_FILENAME).exists()


def test_schema_invalid_config_blocks_apply_without_target_or_marker(tmp_path: Path) -> None:
    source = _build_source_home(tmp_path)
    payload = tomllib.loads((source / "config.toml").read_text(encoding="utf-8"))
    payload["port"] = "not-a-port"
    (source / "config.toml").write_text(tomli_w.dumps(payload), encoding="utf-8")
    target = tmp_path / "target-home"

    report = _run(source, target, apply=True)

    assert any(item["kind"] == "preflight/config" for item in _errors(report))
    assert not target.exists()
    assert not (source / IMPORT_MARKER_FILENAME).exists()


def test_unreadable_sessions_database_blocks_apply(tmp_path: Path) -> None:
    source = _build_source_home(tmp_path)
    (source / "state" / "sessions.db").write_bytes(b"not a sqlite database")
    target = tmp_path / "target-home"

    report = _run(source, target, apply=True)

    assert any(item["kind"] == "preflight/schema" for item in _errors(report))
    assert not target.exists()
    assert not (source / IMPORT_MARKER_FILENAME).exists()


def test_corrupt_secondary_sqlite_store_blocks_dry_run_and_apply(tmp_path: Path) -> None:
    source = _build_source_home(tmp_path)
    corrupt = source / "state" / "approval_queue.sqlite"
    corrupt.write_bytes(b"not a sqlite database")
    target = tmp_path / "target-home"

    preview = _run(source, target, apply=False)
    applied = _run(source, target, apply=True)

    for report in (preview, applied):
        assert any(item["kind"] == "preflight/sqlite" for item in _errors(report))
    assert not target.exists()
    assert not (source / IMPORT_MARKER_FILENAME).exists()


def test_scheduler_pause_failure_aborts_without_target_or_marker(tmp_path: Path) -> None:
    source = _build_source_home(tmp_path)
    connection = sqlite3.connect(source / "state" / "scheduler.db")
    try:
        connection.execute(
            "CREATE TRIGGER reject_pause BEFORE UPDATE OF enabled ON scheduler_jobs "
            "BEGIN SELECT RAISE(ABORT, 'pause rejected'); END"
        )
        connection.commit()
    finally:
        connection.close()
    target = tmp_path / "target-home"

    report = _run(source, target, apply=True)

    assert any(item["kind"] == "scheduler" for item in _errors(report))
    assert not target.exists()
    assert not (source / IMPORT_MARKER_FILENAME).exists()


def test_non_session_target_collision_requires_overwrite(tmp_path: Path) -> None:
    source = _build_source_home(tmp_path)
    target = tmp_path / "target-home"
    (target / "workspace").mkdir(parents=True)
    existing = target / "workspace" / "existing.txt"
    existing.write_text("keep-me", encoding="utf-8")

    report = _run(source, target, apply=True)

    assert any(item["kind"] == "preflight/target" for item in _errors(report))
    assert existing.read_text(encoding="utf-8") == "keep-me"
    assert not (source / IMPORT_MARKER_FILENAME).exists()


def test_overwrite_publish_failure_restores_complete_original_target(
    tmp_path: Path, monkeypatch
) -> None:
    source = _build_source_home(tmp_path)
    target = tmp_path / "target-home"
    (target / "state").mkdir(parents=True)
    (target / "state" / "sessions.db").write_bytes(b"original-session-store")
    (target / "workspace").mkdir()
    (target / "workspace" / "original.txt").write_text("original", encoding="utf-8")
    original_replace = migration_module.os.replace

    def fail_staging_publish(src: str, dst: str) -> None:
        source_path = Path(src)
        destination_path = Path(dst)
        if source_path.name.startswith(".opensquilla-import-") and destination_path == target:
            raise OSError("synthetic publish failure")
        original_replace(src, dst)

    monkeypatch.setattr(migration_module.os, "replace", fail_staging_publish)

    report = _run(source, target, apply=True, overwrite=True)

    assert _errors(report)
    assert (target / "state" / "sessions.db").read_bytes() == b"original-session-store"
    assert (target / "workspace" / "original.txt").read_text(encoding="utf-8") == "original"
    assert not (source / IMPORT_MARKER_FILENAME).exists()


@pytest.mark.parametrize("failed_phase", ["target-backed-up", "published"])
def test_journal_phase_write_failure_rolls_back_complete_original_target(
    tmp_path: Path,
    monkeypatch,
    failed_phase: str,
) -> None:
    source = _build_source_home(tmp_path)
    target = tmp_path / "target-home"
    (target / "state").mkdir(parents=True)
    (target / "state" / "sessions.db").write_bytes(b"original-session-store")
    (target / "workspace").mkdir()
    (target / "workspace" / "original.txt").write_text("original", encoding="utf-8")
    original_atomic_write = migration_module._atomic_write_json

    def fail_phase_write(path: Path, payload: dict[str, Any]) -> None:
        if payload.get("phase") == failed_phase:
            raise OSError(f"synthetic {failed_phase} journal failure")
        original_atomic_write(path, payload)

    monkeypatch.setattr(migration_module, "_atomic_write_json", fail_phase_write)

    report = _run(source, target, apply=True, overwrite=True)

    assert _errors(report)
    assert (target / "state" / "sessions.db").read_bytes() == b"original-session-store"
    assert (target / "workspace" / "original.txt").read_text(encoding="utf-8") == "original"
    assert not list(tmp_path.glob("target-home.backup.*"))
    assert not (tmp_path / ".target-home.import-commit.json").exists()
    assert list(tmp_path.glob(".opensquilla-import-*"))
    assert not (source / IMPORT_MARKER_FILENAME).exists()


def test_dry_run_config_compatibility_pass_has_no_global_side_effects(
    tmp_path: Path, monkeypatch
) -> None:
    source = _build_source_home(tmp_path)
    target = tmp_path / "target-home"
    diagnostics_home = tmp_path / "diagnostics-home"
    monkeypatch.setattr(
        config_migration_module,
        "default_opensquilla_home",
        lambda: diagnostics_home,
    )
    memory_warned = config_migration_module._LEGACY_MEMORY_FIELDS_WARNED
    memory_seen = set(config_migration_module._LEGACY_MEMORY_FIELDS_SEEN)
    token_warned = config_migration_module._LEGACY_AGENT_TOKEN_SAVING_FIELDS_WARNED
    token_seen = set(config_migration_module._LEGACY_AGENT_TOKEN_SAVING_FIELDS_SEEN)

    report = _run(source, target)

    assert not _errors(report)
    assert not diagnostics_home.exists()
    assert config_migration_module._LEGACY_MEMORY_FIELDS_WARNED is memory_warned
    assert config_migration_module._LEGACY_MEMORY_FIELDS_SEEN == memory_seen
    assert config_migration_module._LEGACY_AGENT_TOKEN_SAVING_FIELDS_WARNED is token_warned
    assert config_migration_module._LEGACY_AGENT_TOKEN_SAVING_FIELDS_SEEN == token_seen


def _write_simple_sqlite(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE payload (value TEXT NOT NULL)")
        connection.execute("INSERT INTO payload VALUES (?)", (value,))
        connection.commit()
    finally:
        connection.close()


def test_all_imported_sqlite_stores_have_consistent_pristine_snapshots(
    tmp_path: Path,
) -> None:
    source = _build_source_home(tmp_path)
    _write_simple_sqlite(source / "state" / "approval_queue.sqlite", "approval")
    _write_simple_sqlite(source / "state" / "sandbox_user_grants.sqlite", "sandbox")
    _write_simple_sqlite(source / "state" / "agents" / "main" / "memory.db", "memory")
    target = tmp_path / "target-home"

    report = _run(source, target, apply=True)

    assert not _errors(report)
    snapshots = Path(report["output_dir"]) / "db-snapshots"
    expected = [
        Path("sessions.db"),
        Path("scheduler.db"),
        Path("approval_queue.sqlite"),
        Path("sandbox_user_grants.sqlite"),
        Path("agents/main/memory.db"),
    ]
    for relative in expected:
        snapshot = snapshots / relative
        assert snapshot.is_file(), relative
        connection = sqlite3.connect(snapshot)
        try:
            assert connection.execute("PRAGMA quick_check").fetchone() == ("ok",)
        finally:
            connection.close()


def test_wal_only_committed_row_survives_as_normalized_sqlite_snapshot(
    tmp_path: Path,
) -> None:
    source = _build_source_home(tmp_path)
    db_path = source / "state" / "sessions.db"
    writer = sqlite3.connect(db_path)
    try:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("CREATE TABLE wal_payload (value TEXT NOT NULL)")
        writer.commit()
        writer.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        writer.execute("INSERT INTO wal_payload VALUES ('committed-in-wal')")
        writer.commit()
        assert db_path.with_name("sessions.db-wal").stat().st_size > 0
        source_before = _file_bytes(source)

        target = tmp_path / "target-home"
        report = _run(source, target, apply=True)
        source_after = _file_bytes(source)
        source_after.pop(IMPORT_MARKER_FILENAME)
    finally:
        writer.close()

    assert not _errors(report)
    assert source_after == source_before
    target_db = target / "state" / "sessions.db"
    assert not target_db.with_name("sessions.db-wal").exists()
    assert not target_db.with_name("sessions.db-shm").exists()
    connection = sqlite3.connect(target_db)
    try:
        assert connection.execute("SELECT value FROM wal_payload").fetchall() == [
            ("committed-in-wal",)
        ]
        assert connection.execute("PRAGMA quick_check").fetchone() == ("ok",)
    finally:
        connection.close()


def test_complete_wal_bundle_wins_over_identical_duplicate_base_database(
    tmp_path: Path,
) -> None:
    source = _build_source_home(tmp_path)
    canonical_db = source / "state" / "sessions.db"
    connection = sqlite3.connect(canonical_db)
    try:
        assert connection.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
        connection.execute("PRAGMA wal_autocheckpoint=0")
        connection.execute("CREATE TABLE wal_bundle_payload (value TEXT NOT NULL)")
        connection.commit()
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        connection.close()

    external_state = tmp_path / "external-state"
    external_state.mkdir()
    external_db = external_state / "sessions.db"
    shutil.copy2(canonical_db, external_db)
    writer = sqlite3.connect(external_db)
    try:
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("INSERT INTO wal_bundle_payload VALUES ('committed-in-external-wal')")
        writer.commit()
        assert external_db.with_name("sessions.db-wal").stat().st_size > 32
        assert canonical_db.read_bytes() == external_db.read_bytes()
        payload = tomllib.loads((source / "config.toml").read_text(encoding="utf-8"))
        payload["state_dir"] = str(external_state)
        (source / "config.toml").write_text(tomli_w.dumps(payload), encoding="utf-8")
        target = tmp_path / "target-home"

        report = _run(source, target, apply=True)
    finally:
        writer.close()

    assert not _errors(report)
    target_connection = sqlite3.connect(target / "state" / "sessions.db")
    try:
        assert target_connection.execute("SELECT value FROM wal_bundle_payload").fetchall() == [
            ("committed-in-external-wal",)
        ]
    finally:
        target_connection.close()


def test_logically_conflicting_duplicate_sqlite_roots_fail_closed(tmp_path: Path) -> None:
    source = _build_source_home(tmp_path)
    canonical_db = source / "state" / "sessions.db"
    external_state = tmp_path / "external-state"
    external_state.mkdir()
    external_db = external_state / "sessions.db"
    shutil.copy2(canonical_db, external_db)
    connection = sqlite3.connect(external_db)
    try:
        connection.execute("CREATE TABLE divergent_payload (value TEXT NOT NULL)")
        connection.execute("INSERT INTO divergent_payload VALUES ('external-only')")
        connection.commit()
    finally:
        connection.close()
    payload = tomllib.loads((source / "config.toml").read_text(encoding="utf-8"))
    payload["state_dir"] = str(external_state)
    (source / "config.toml").write_text(tomli_w.dumps(payload), encoding="utf-8")
    target = tmp_path / "target-home"

    report = _run(source, target, apply=True)

    assert any(
        item["kind"] == "preflight/data-root"
        and "conflicting logical SQLite stores" in item["reason"]
        for item in _errors(report)
    )
    assert not target.exists()
    assert not (source / IMPORT_MARKER_FILENAME).exists()


def test_conflicting_split_state_roots_fail_without_publishing(tmp_path: Path) -> None:
    source = _build_source_home(tmp_path)
    (source / "state" / "collision.bin").write_bytes(b"canonical")
    external_state = tmp_path / "external-state"
    external_state.mkdir()
    (external_state / "collision.bin").write_bytes(b"external")
    payload = tomllib.loads((source / "config.toml").read_text(encoding="utf-8"))
    payload["state_dir"] = str(external_state)
    (source / "config.toml").write_text(tomli_w.dumps(payload), encoding="utf-8")
    target = tmp_path / "target-home"

    preview = _run(source, target, apply=False)
    report = _run(source, target, apply=True)

    for result in (preview, report):
        assert any(item["kind"] == "preflight/data-root" for item in _errors(result))
    assert not target.exists()
    assert not (source / IMPORT_MARKER_FILENAME).exists()


def test_interrupted_overwrite_is_restored_before_retry(tmp_path: Path) -> None:
    source = _build_source_home(tmp_path)
    target = tmp_path / "target-home"
    interrupted_backup = tmp_path / "target-home.backup.interrupted"
    (interrupted_backup / "workspace").mkdir(parents=True)
    (interrupted_backup / "workspace" / "original.txt").write_text(
        "original", encoding="utf-8"
    )
    interrupted_staging = tmp_path / ".opensquilla-import-interrupted"
    interrupted_staging.mkdir()
    (interrupted_staging / "partial.txt").write_text("partial", encoding="utf-8")
    journal = tmp_path / ".target-home.import-commit.json"
    journal.write_text(
        json.dumps(
            {
                "target": str(target),
                "staging": str(interrupted_staging),
                "backup": str(interrupted_backup),
                "phase": "target-backed-up",
                "target_existed": True,
            }
        ),
        encoding="utf-8",
    )

    report = _run(source, target, apply=True, overwrite=True)

    assert not _errors(report)
    assert any(item["kind"] == "recovery" for item in report["items"])
    assert not journal.exists()
    assert not interrupted_staging.exists()
    assert not interrupted_backup.exists()
    backups = list(tmp_path.glob("target-home.backup.*"))
    assert len(backups) == 1
    assert (backups[0] / "workspace" / "original.txt").read_text(
        encoding="utf-8"
    ) == "original"
    assert (target / "workspace" / "MEMORY.md").is_file()


def test_dry_run_reports_interrupted_commit_without_mutating_it(tmp_path: Path) -> None:
    source = _build_source_home(tmp_path)
    target = tmp_path / "target-home"
    backup = tmp_path / "target-home.backup.interrupted"
    backup.mkdir()
    staging = tmp_path / ".opensquilla-import-interrupted"
    staging.mkdir()
    journal = tmp_path / ".target-home.import-commit.json"
    payload = {
        "target": str(target),
        "staging": str(staging),
        "backup": str(backup),
        "phase": "target-backed-up",
        "target_existed": True,
    }
    journal.write_text(json.dumps(payload), encoding="utf-8")

    report = _run(source, target, apply=False)

    assert any(item["kind"] == "preflight/recovery" for item in _errors(report))
    assert json.loads(journal.read_text(encoding="utf-8")) == payload
    assert backup.is_dir()
    assert staging.is_dir()
    assert not target.exists()


@pytest.mark.asyncio
async def test_real_session_transcript_workspace_and_media_survive_import(
    tmp_path: Path,
) -> None:
    source = tmp_path / "legacy-home"
    source.mkdir()
    _write_config(source)
    source_db = source / "state" / "sessions.db"
    source_db.parent.mkdir(parents=True)
    apply_pending(f"sqlite:///{source_db}", MIGRATIONS_DIR)
    storage = SessionStorage(str(source_db))
    await storage.connect()
    try:
        manager = SessionManager(storage, inject_time_prefix=False, media_root=source / "media")
        session = await manager.create("agent:main:direct:migration-e2e")
        for role, content in (("user", "synthetic user prompt"), ("assistant", "synthetic reply")):
            await storage.append_transcript_entry(
                TranscriptEntry(
                    session_id=session.session_id,
                    session_key=session.session_key,
                    role=role,
                    content=content,
                    token_count=3,
                )
            )
    finally:
        await storage.close()

    (source / "workspace").mkdir()
    (source / "workspace" / "important.txt").write_text(
        "workspace survives", encoding="utf-8"
    )
    attachment_sha, _path, _wrote = write_transcript_material(
        media_root=source / "media",
        session_id=session.session_id,
        payload=b"attachment survives",
    )
    artifact = ArtifactStore(source / "media").publish_bytes(
        b"artifact survives",
        session_id=session.session_id,
        session_key=session.session_key,
        name="result.bin",
        mime="application/octet-stream",
        source="migration-test",
    )
    _write_scheduler_db(source, with_enabled_column=True)
    target = tmp_path / "target-home"

    report = _run(source, target, apply=True)

    assert not _errors(report)
    apply_pending(f"sqlite:///{target / 'state' / 'sessions.db'}", MIGRATIONS_DIR)
    reopened = SessionStorage(str(target / "state" / "sessions.db"))
    await reopened.connect()
    try:
        restored = await reopened.get_session(session.session_key)
        assert restored is not None
        transcript = await reopened.get_transcript(session.session_id)
        assert [(entry.role, entry.content) for entry in transcript] == [
            ("user", "synthetic user prompt"),
            ("assistant", "synthetic reply"),
        ]
    finally:
        await reopened.close()

    assert (target / "workspace" / "important.txt").read_text(
        encoding="utf-8"
    ) == "workspace survives"
    attachment_ref = make_attachment_ref(
        sha256=attachment_sha,
        name="upload.bin",
        mime="application/octet-stream",
        size=len(b"attachment survives"),
        session_id=session.session_id,
        source="transcript",
    )
    assert read_attachment_ref_bytes(attachment_ref, media_root=target / "media") == (
        b"attachment survives"
    )
    _ref, artifact_path = ArtifactStore(target / "media").resolve_for_download(
        artifact.id, session_id=session.session_id
    )
    assert artifact_path.read_bytes() == b"artifact survives"
    assert _scheduler_enabled_values(target / "state" / "scheduler.db") == [0]


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
