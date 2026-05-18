"""Repro: daily memory living in a sibling workspace (workspace-wN) is dropped.

Mirrors the real openclaw home layout we see in the wild, where openclaw.json
omits agents.defaults.workspace and the user actually has multiple sibling
workspace directories. The migrator currently only inspects the primary
workspace, so daily memory in any workspace-wN/memory/ is silently lost.
"""
from __future__ import annotations

import json
from pathlib import Path

from opensquilla.migration.openclaw import MigrationOptions, OpenClawMigrator


def _make_multi_workspace_source(root: Path) -> Path:
    source = root / ".openclaw"
    # primary workspace: no memory/ subdir, mirrors real-world layout
    (source / "workspace").mkdir(parents=True)
    (source / "workspace" / "SOUL.md").write_text("primary soul\n", encoding="utf-8")
    (source / "workspace" / "USER.md").write_text("primary user\n", encoding="utf-8")
    # sibling workspace-w4 with the daily memory we expect to see migrated
    (source / "workspace-w4" / "memory").mkdir(parents=True)
    (source / "workspace-w4" / "SOUL.md").write_text("w4 soul\n", encoding="utf-8")
    (source / "workspace-w4" / "memory" / "2026-05-04.md").write_text(
        "daily note from workspace-w4\n",
        encoding="utf-8",
    )
    (source / "workspace-w4" / "memory" / "2026-05-05.md").write_text(
        "another daily note from workspace-w4\n",
        encoding="utf-8",
    )
    # config: no agents.defaults.workspace, so the migrator falls back to source/workspace
    (source / "openclaw.json").write_text(
        json.dumps(
            {
                "agents": {"defaults": {"model": {"primary": "x"}}},
                "meta": {"lastTouchedVersion": "2026.4.24"},
            }
        ),
        encoding="utf-8",
    )
    return source


def test_daily_memory_in_sibling_workspace_should_migrate(tmp_path, monkeypatch):
    source = _make_multi_workspace_source(tmp_path)
    home = tmp_path / "opensquilla-home"
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(home))

    report = OpenClawMigrator(
        MigrationOptions(
            source=source, config_path=tmp_path / "config.toml", apply=True
        )
    ).migrate()

    memory_target = home / "workspace" / "MEMORY.md"
    text = memory_target.read_text(encoding="utf-8") if memory_target.is_file() else ""

    # demonstrate the failure: daily memory should be in the migrated MEMORY.md
    assert "daily note from workspace-w4" in text, (
        f"daily memory from workspace-w4 was dropped.\n"
        f"MEMORY.md content:\n{text!r}\n"
        f"memory item record: "
        f"{next((i for i in report['items'] if i['kind']=='memory'), None)}"
    )
    assert "another daily note from workspace-w4" in text
    # daily-memory headers from sibling workspaces are prefixed with the
    # workspace directory name so multiple workspaces can have the same date
    # without colliding.
    assert "## Imported daily memory: workspace-w4/2026-05-04.md" in text


def test_sibling_dirs_without_workspace_markers_are_ignored(tmp_path, monkeypatch):
    # workspace-trash/ has a memory/ subdir with daily notes but none of the
    # persona marker files (SOUL.md/USER.md/AGENTS.md/IDENTITY.md/MEMORY.md),
    # so it should be rejected as not-a-workspace.
    source = tmp_path / ".openclaw"
    (source / "workspace").mkdir(parents=True)
    (source / "workspace" / "SOUL.md").write_text("primary\n", encoding="utf-8")
    (source / "workspace" / "memory").mkdir()
    (source / "workspace" / "memory" / "2026-05-01.md").write_text(
        "primary daily note\n", encoding="utf-8"
    )
    # decoy: name matches but no persona markers
    (source / "workspace-trash" / "memory").mkdir(parents=True)
    (source / "workspace-trash" / "memory" / "2026-05-02.md").write_text(
        "should not be migrated\n", encoding="utf-8"
    )
    (source / "openclaw.json").write_text("{}", encoding="utf-8")
    home = tmp_path / "opensquilla-home"
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(home))

    report = OpenClawMigrator(
        MigrationOptions(
            source=source, config_path=tmp_path / "config.toml", apply=True
        )
    ).migrate()

    text = (home / "workspace" / "MEMORY.md").read_text(encoding="utf-8")
    assert "primary daily note" in text
    assert "should not be migrated" not in text
    item = next(i for i in report["items"] if i["kind"] == "memory")
    assert all(
        "workspace-trash" not in src for src in item["details"]["read_sources"]
    )


def test_memory_report_lists_all_read_sources(tmp_path, monkeypatch):
    source = _make_multi_workspace_source(tmp_path)
    home = tmp_path / "opensquilla-home"
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(home))

    report = OpenClawMigrator(
        MigrationOptions(
            source=source, config_path=tmp_path / "config.toml", apply=True
        )
    ).migrate()

    item = next(i for i in report["items"] if i["kind"] == "memory")
    sources = item["details"]["read_sources"]
    normalized_sources = [s.replace("\\", "/") for s in sources]
    assert any(
        s.endswith("workspace-w4/memory/2026-05-04.md") for s in normalized_sources
    )
    assert any(
        s.endswith("workspace-w4/memory/2026-05-05.md") for s in normalized_sources
    )
    assert len(sources) == 2
