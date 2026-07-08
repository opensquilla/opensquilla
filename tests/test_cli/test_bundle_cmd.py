"""``opensquilla bundle`` — offline diagnostics bundle collection.

Offline: state/log dirs point at tmp_path; no gateway needs to run (live
enrichment is best-effort and silently skipped, and stubbed out here for
determinism). An autouse fixture also pins OPENSQUILLA_GATEWAY_CONFIG_PATH
to a synthetic TOML so no test can ever read or rewrite a real config.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from opensquilla.cli.main import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def _hermetic_offline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin config resolution to a synthetic file and stub live enrichment.

    Without the config pin, resolve_config_path(None) falls back to
    ./opensquilla.toml and then the developer's real home config — which the
    bundle's doctor collector must never see. The enrichment stub keeps tests
    deterministic and fast instead of relying on a quick connection failure.
    """
    config_path = tmp_path / "synthetic-config.toml"
    config_path.write_text("# synthetic bundle-cmd test config\n", encoding="utf-8")
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(config_path))
    try:
        from opensquilla.cli import bundle_cmd
    except ImportError:
        # First TDD run: module does not exist yet; let the CLI invocation
        # fail with "No such command" instead of a fixture error.
        return
    monkeypatch.setattr(bundle_cmd, "_live_enrichment", lambda: {})


def test_bundle_writes_zip_and_prints_path(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    (home / "logs").mkdir(parents=True)
    (home / "logs" / "debug.log").write_text("2026-07-07 [INFO] opensquilla: ok\n")
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(home))
    monkeypatch.setenv("OPENSQUILLA_LOG_DIR", str(home / "logs"))
    output = tmp_path / "out.zip"

    result = runner.invoke(app, ["bundle", "--output", str(output)])

    assert result.exit_code == 0, result.output
    assert output.exists()
    assert str(output) in result.stdout
    with zipfile.ZipFile(output) as archive:
        assert "manifest.json" in archive.namelist()


def test_bundle_json_output(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    (home / "logs").mkdir(parents=True)
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(home))
    monkeypatch.setenv("OPENSQUILLA_LOG_DIR", str(home / "logs"))
    output = tmp_path / "out.zip"

    result = runner.invoke(app, ["bundle", "--output", str(output), "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["path"].endswith("out.zip")
    assert payload["bundle_schema"] == 1


def test_bundle_include_content_flag(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    (home / "logs").mkdir(parents=True)
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(home))
    monkeypatch.setenv("OPENSQUILLA_LOG_DIR", str(home / "logs"))
    output = tmp_path / "out.zip"

    result = runner.invoke(app, ["bundle", "--output", str(output), "--include-content"])

    assert result.exit_code == 0, result.output
    with zipfile.ZipFile(output) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    assert manifest["content_tier"] is True
