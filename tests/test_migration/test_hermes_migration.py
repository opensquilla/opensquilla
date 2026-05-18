from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

from opensquilla.migration.hermes import HermesMigrationOptions, HermesMigrator


def _make_hermes_home(root: Path) -> Path:
    home = root / ".hermes"
    home.mkdir(parents=True)
    (home / "config.yaml").write_text("model:\n  provider: openrouter\n", encoding="utf-8")
    return home


def test_source_detection_prefers_explicit_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    explicit = _make_hermes_home(tmp_path / "explicit")
    env_home = _make_hermes_home(tmp_path / "env")
    monkeypatch.setenv("HERMES_HOME", str(env_home))

    migrator = HermesMigrator(HermesMigrationOptions(source=explicit))

    assert migrator.source == explicit


def test_source_detection_uses_hermes_home_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_home = _make_hermes_home(tmp_path / "env")
    monkeypatch.setenv("HERMES_HOME", str(env_home))

    migrator = HermesMigrator(HermesMigrationOptions())

    assert migrator.source == env_home


def test_source_detection_uses_profile_under_root_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _make_hermes_home(tmp_path)
    profile = root / "profiles" / "work"
    profile.mkdir(parents=True)
    (profile / "config.yaml").write_text("model:\n  provider: anthropic\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(root))

    migrator = HermesMigrator(HermesMigrationOptions(profile="work"))

    assert migrator.source == profile


def test_dry_run_plans_user_data_without_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _make_hermes_home(tmp_path)
    (source / "SOUL.md").write_text("Hermes soul\n", encoding="utf-8")
    memories = source / "memories"
    memories.mkdir()
    (memories / "MEMORY.md").write_text("memory line\n", encoding="utf-8")
    (memories / "USER.md").write_text("user profile\n", encoding="utf-8")
    (source / "skills" / "demo").mkdir(parents=True)
    (source / "skills" / "demo" / "SKILL.md").write_text(
        "---\nname: demo\ndescription: Demo\n---\nBody\n",
        encoding="utf-8",
    )
    home = tmp_path / "opensquilla-home"
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(home))

    report = HermesMigrator(HermesMigrationOptions(source=source, apply=False)).migrate()

    statuses = {(item["kind"], item["status"]) for item in report["items"]}
    assert ("soul", "planned") in statuses
    assert ("memory", "planned") in statuses
    assert ("user-profile", "planned") in statuses
    assert ("skills", "planned") in statuses
    assert not (home / "workspace" / "SOUL.md").exists()
    assert not (home / "skills" / "hermes-imports").exists()


def test_apply_migrates_user_data_and_skills(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _make_hermes_home(tmp_path)
    (source / "SOUL.md").write_text("Hermes soul\n", encoding="utf-8")
    memories = source / "memories"
    memories.mkdir()
    (memories / "MEMORY.md").write_text("memory line\n", encoding="utf-8")
    (memories / "USER.md").write_text("user profile\n", encoding="utf-8")
    skill = source / "skills" / "demo"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: demo\ndescription: Demo\n---\nBody\n", encoding="utf-8"
    )
    home = tmp_path / "opensquilla-home"
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(home))

    report = HermesMigrator(HermesMigrationOptions(source=source, apply=True)).migrate()

    assert (home / "workspace" / "SOUL.md").read_text(encoding="utf-8") == "Hermes soul\n"
    assert "memory line" in (home / "workspace" / "MEMORY.md").read_text(encoding="utf-8")
    assert (home / "workspace" / "USER.md").read_text(encoding="utf-8") == "user profile\n"
    assert (home / "skills" / "hermes-imports" / "demo" / "SKILL.md").is_file()
    assert (Path(report["output_dir"]) / "report.json").is_file()
    assert (Path(report["output_dir"]) / "summary.md").is_file()


def test_apply_maps_config_env_channels_and_mcp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _make_hermes_home(tmp_path)
    (source / "config.yaml").write_text(
        """
model:
  provider: anthropic
  model: claude-3-5-sonnet-latest
  base_url: https://anthropic.example.test/v1
mcp:
  servers:
    docs:
      url: http://127.0.0.1:8765/sse
    filesystem:
      command: node
      args: ["server.js"]
      env:
        NODE_ENV: test
telegram:
  default_chat_id: "123"
discord:
  default_channel_id: "456"
slack:
  channel_id: "C789"
""",
        encoding="utf-8",
    )
    (source / ".env").write_text(
        "\n".join(
            [
                "ANTHROPIC_API_KEY=sk-ant-secret",
                "BRAVE_API_KEY=brave-secret",
                "TELEGRAM_BOT_TOKEN=tg-secret",
                "DISCORD_BOT_TOKEN=discord-secret",
                "SLACK_BOT_TOKEN=slack-secret",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (source / "skills" / "demo").mkdir(parents=True)
    (source / "skills" / "demo" / "SKILL.md").write_text(
        "---\nname: demo\ndescription: Demo\n---\n",
        encoding="utf-8",
    )
    home = tmp_path / "opensquilla-home"
    config_path = tmp_path / "opensquilla.toml"
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(home))

    report = HermesMigrator(
        HermesMigrationOptions(
            source=source,
            config_path=config_path,
            apply=True,
            migrate_secrets=True,
        )
    ).migrate()

    config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert config["llm"]["provider"] == "anthropic"
    assert config["llm"]["model"] == "claude-3-5-sonnet-latest"
    assert config["llm"]["api_key_env"] == "ANTHROPIC_API_KEY"
    assert config["llm"]["base_url"] == "https://anthropic.example.test/v1"
    assert config["search_provider"] == "brave"
    assert config["search_api_key_env"] == "BRAVE_SEARCH_API_KEY"
    assert str(home / "skills" / "hermes-imports") in config["skills"]["extra_dirs"]
    assert config["mcp"]["enabled"] is True
    assert {entry["name"] for entry in config["mcp"]["servers"]} == {"docs", "filesystem"}
    channels = {entry["type"]: entry for entry in config["channels"]["channels"]}
    assert channels["telegram"]["token"] == "tg-secret"
    assert channels["telegram"]["default_chat_id"] == "123"
    assert channels["discord"]["token"] == "discord-secret"
    assert channels["discord"]["default_channel_id"] == "456"
    assert channels["slack"]["token"] == "slack-secret"
    assert channels["slack"]["slack_channel_id"] == "C789"
    assert "sk-ant-secret" not in json.dumps(report)
    assert "ANTHROPIC_API_KEY=sk-ant-secret" in (home / ".env").read_text(encoding="utf-8")
    assert "BRAVE_SEARCH_API_KEY=brave-secret" in (home / ".env").read_text(
        encoding="utf-8"
    )


def test_custom_provider_with_base_url_maps_to_openai_compatible_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _make_hermes_home(tmp_path)
    (source / "config.yaml").write_text(
        """
model:
  provider: custom
  default: e2e-local
  base_url: http://127.0.0.1:48921/v1
""",
        encoding="utf-8",
    )
    home = tmp_path / "opensquilla-home"
    config_path = tmp_path / "opensquilla.toml"
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(home))

    HermesMigrator(
        HermesMigrationOptions(source=source, config_path=config_path, apply=True)
    ).migrate()

    config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert config["llm"]["provider"] == "openai"
    assert config["llm"]["api_key_env"] == "OPENAI_API_KEY"
    assert config["llm"]["model"] == "e2e-local"
    assert config["llm"]["base_url"] == "http://127.0.0.1:48921/v1"


def test_archive_unsupported_runtime_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _make_hermes_home(tmp_path)
    (source / "state.db").write_bytes(b"SQLite format 3\x00")
    (source / "auth.json").write_text('{"token": "do-not-copy"}', encoding="utf-8")
    (source / "cron").mkdir()
    (source / "cron" / "jobs.json").write_text('{"jobs": []}', encoding="utf-8")
    (source / "logs").mkdir()
    (source / "logs" / "run.log").write_text("log line\n", encoding="utf-8")
    home = tmp_path / "opensquilla-home"
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(home))

    report = HermesMigrator(HermesMigrationOptions(source=source, apply=True)).migrate()

    output_dir = Path(report["output_dir"])
    assert (output_dir / "archive" / "files" / "cron" / "jobs.json").is_file()
    assert not (output_dir / "archive" / "files" / "state.db").exists()
    assert not (output_dir / "archive" / "files" / "auth.json").exists()
    assert not (output_dir / "archive" / "files" / "logs" / "run.log").exists()
    statuses = {(item["kind"], item["status"]) for item in report["items"]}
    assert ("state.db", "skipped") in statuses
    assert ("auth.json", "skipped") in statuses
    assert ("logs", "skipped") in statuses
    assert ("cron-jobs", "archived") in statuses
