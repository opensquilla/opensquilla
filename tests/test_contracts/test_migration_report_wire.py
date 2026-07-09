"""Wire-shape contract for the OpenSquilla self-migration report.

Pins the top-level key set and value types of the report dict produced by
``OpenSquillaHomeMigrator.migrate()`` (see
``docs/self-migration-report-contract.md``): changes must be additive only,
and secret relocations must never carry the secret value.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from opensquilla.migration.opensquilla_home import (
    OpenSquillaHomeMigrator,
    OpenSquillaMigrationOptions,
)

DUMMY_SECRET = "dummy-secret-value-123"

EXPECTED_TYPES: dict[str, type | tuple[type, ...]] = {
    "source": str,
    "source_kind": str,
    "target": str,
    "output_dir": str,
    "apply": bool,
    "items": list,
    "candidates": list,
    "config_transforms": list,
    "secret_relocations": list,
    "paused_jobs": list,
    "preflight": dict,
    "notes": list,
}

PREFLIGHT_TYPES: dict[str, type | tuple[type, ...]] = {
    "source_gateway_running": bool,
    "target_gateway_running": bool,
    "schema_ahead": bool,
    "disk_required_bytes": int,
    "disk_free_bytes": int,
}


def _minimal_home(root: Path) -> Path:
    home = root / "legacy-home"
    (home / "workspace").mkdir(parents=True)
    (home / "workspace" / "MEMORY.md").write_text("# Memory index\n", encoding="utf-8")
    (home / "config.toml").write_text(
        "port = 18790\n"
        "\n"
        "[llm]\n"
        'provider = "openrouter"\n'
        'model = "dummy/dummy-model"\n'
        f'api_key = "{DUMMY_SECRET}"\n',
        encoding="utf-8",
    )
    return home


def _dry_run_report(tmp_path: Path) -> dict[str, Any]:
    options = OpenSquillaMigrationOptions(
        source=_minimal_home(tmp_path),
        target=tmp_path / "target-home",
        apply=False,
    )
    return OpenSquillaHomeMigrator(options).migrate()


def test_report_top_level_keys_and_types(tmp_path: Path) -> None:
    report = _dry_run_report(tmp_path)

    assert set(report) == set(EXPECTED_TYPES)
    for key, expected_type in EXPECTED_TYPES.items():
        assert isinstance(report[key], expected_type), key
    # bool is an int subclass; the flag must really be a bool.
    assert report["apply"] is False

    assert set(report["preflight"]) == set(PREFLIGHT_TYPES)
    for key, expected_type in PREFLIGHT_TYPES.items():
        value = report["preflight"][key]
        assert isinstance(value, expected_type), key
        if expected_type is int:
            assert not isinstance(value, bool), key

    assert report["output_dir"] == ""
    assert report["source_kind"] == "cli-home"

    for item in report["items"]:
        assert {"kind", "source", "destination", "status", "reason", "details"} <= set(item)
        assert item["status"] in {"migrated", "planned", "skipped", "error"}


def test_secret_relocations_are_redacted(tmp_path: Path) -> None:
    report = _dry_run_report(tmp_path)

    relocations = report["secret_relocations"]
    assert relocations, "the inline llm.api_key must produce a relocation plan"
    for entry in relocations:
        assert set(entry) == {"config_path", "env_key", "moved"}
        assert entry["moved"] is True
        assert isinstance(entry["config_path"], str)
        assert isinstance(entry["env_key"], str)

    assert DUMMY_SECRET not in json.dumps(report)
