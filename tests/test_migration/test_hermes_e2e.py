from __future__ import annotations

import json
import tomllib
from pathlib import Path

from typer.testing import CliRunner

from opensquilla.cli.main import app
from opensquilla.onboarding.config_store import load_config

runner = CliRunner()


def _write_hermes_home(root: Path) -> Path:
    source = root / ".hermes"
    source.mkdir(parents=True)
    (source / "config.yaml").write_text(
        "model:\n  provider: openrouter\n  model: openai/gpt-4o-mini\n",
        encoding="utf-8",
    )
    (source / "SOUL.md").write_text("Hermes soul\n", encoding="utf-8")
    return source


def test_cli_hermes_dry_run_json_does_not_write(tmp_path: Path, monkeypatch) -> None:
    source = _write_hermes_home(tmp_path)
    home = tmp_path / "opensquilla-home"
    config_path = tmp_path / "opensquilla.toml"
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(home))

    result = runner.invoke(
        app,
        ["migrate", "hermes", "--source", str(source), "--config", str(config_path), "--json"],
    )

    assert result.exit_code == 0, result.stdout
    report = json.loads(result.stdout)
    assert report["apply"] is False
    assert not config_path.exists()
    assert not (home / "workspace" / "SOUL.md").exists()


def test_cli_hermes_apply_preserves_existing_config_and_redacts_report(
    tmp_path: Path, monkeypatch
) -> None:
    source = _write_hermes_home(tmp_path)
    (source / ".env").write_text(
        "OPENROUTER_API_KEY=sk-or-secret\nTELEGRAM_BOT_TOKEN=tg-secret\n",
        encoding="utf-8",
    )
    (source / "config.yaml").write_text(
        """
model:
  provider: openrouter
  model: anthropic/claude-3.5-sonnet
telegram:
  default_chat_id: "123"
""",
        encoding="utf-8",
    )
    home = tmp_path / "opensquilla-home"
    config_path = tmp_path / "opensquilla.toml"
    config_path.write_text('host = "127.0.0.9"\nport = 19999\n', encoding="utf-8")
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(home))

    result = runner.invoke(
        app,
        [
            "migrate",
            "hermes",
            "--source",
            str(source),
            "--config",
            str(config_path),
            "--apply",
            "--migrate-secrets",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    report = json.loads(result.stdout)
    assert "sk-or-secret" not in result.stdout
    assert "tg-secret" not in result.stdout
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert config["host"] == "127.0.0.9"
    assert config["port"] == 19999
    # Sparse persistence omits values equal to the built-in default
    # (provider "openrouter"); the effective provider must still resolve
    # to the migrated value.
    assert config["llm"].get("provider", "openrouter") == "openrouter"
    assert load_config(config_path).llm.provider == "openrouter"
    assert config["llm"]["model"] == "anthropic/claude-3.5-sonnet"
    assert config["channels"]["channels"][0]["type"] == "telegram"
    assert (Path(report["output_dir"]) / "report.json").is_file()
