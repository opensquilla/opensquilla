"""Tests for shared migration orchestration."""

from __future__ import annotations

from pathlib import Path

import pytest

from opensquilla.migration import orchestrator


def test_run_migration_batch_uses_canonical_source_order(monkeypatch, tmp_path):
    detected = [
        orchestrator.DetectedMigrationSource("openclaw", tmp_path / ".openclaw"),
        orchestrator.DetectedMigrationSource("hermes", tmp_path / ".hermes"),
    ]
    calls: list[tuple[str, Path]] = []

    def fake_run_one_migration(name, source_path, options):
        calls.append((name, source_path))
        return {
            "output_dir": str(tmp_path / "reports" / name),
            "items": [{"kind": "config", "status": "planned"}],
        }

    monkeypatch.setattr(orchestrator, "run_one_migration", fake_run_one_migration)

    result = orchestrator.run_migration_batch(
        detected,
        ["hermes", "openclaw"],
        orchestrator.MigrationBatchOptions(apply=False),
    )

    assert result.selected == ("openclaw", "hermes")
    assert [name for name, _path in calls] == ["openclaw", "hermes"]
    assert result.has_error is False


def test_run_migration_batch_validates_all_sources_before_running(monkeypatch, tmp_path):
    detected = [
        orchestrator.DetectedMigrationSource("openclaw", tmp_path / ".openclaw"),
        orchestrator.DetectedMigrationSource("hermes", tmp_path / ".hermes"),
    ]

    def fake_run_one_migration(*_args, **_kwargs):
        raise AssertionError("should validate before running any migrator")

    monkeypatch.setattr(orchestrator, "run_one_migration", fake_run_one_migration)

    with pytest.raises(orchestrator.MigrationOptionError):
        orchestrator.run_migration_batch(
            detected,
            ["openclaw", "hermes"],
            orchestrator.MigrationBatchOptions(persona_conflict="bogus"),
        )


def test_opensquilla_batch_rejects_custom_config_path(tmp_path: Path) -> None:
    with pytest.raises(orchestrator.MigrationOptionError, match="--config"):
        orchestrator.validate_batch_options(
            ("opensquilla",),
            orchestrator.MigrationBatchOptions(config=tmp_path / "custom.toml"),
        )
