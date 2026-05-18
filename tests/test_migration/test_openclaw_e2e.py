from __future__ import annotations

import json
import tomllib
from pathlib import Path

from typer.testing import CliRunner

from opensquilla.cli.main import app
from opensquilla.gateway.config import (
    AgentEntryConfig,
    AuthConfig,
    GatewayConfig,
    RateLimitConfig,
    SafetyConfig,
    TaskRuntimeConfig,
)
from opensquilla.onboarding.config_store import persist_config

runner = CliRunner()


def _write_realistic_openclaw_home(root: Path) -> Path:
    source = root / ".openclaw"
    workspace = source / "ops-workspace"
    (workspace / "memory").mkdir(parents=True)
    (workspace / "skills" / "triage").mkdir(parents=True)
    (workspace / ".agents" / "skills" / "workspace-local").mkdir(parents=True)
    (workspace / "tts" / "voices").mkdir(parents=True)
    (workspace / "hooks").mkdir(parents=True)
    (source / "workspace.default").mkdir(parents=True)
    (source / "skills" / "research").mkdir(parents=True)
    (source / "extensions" / "legacy-plugin").mkdir(parents=True)
    (source / "cron").mkdir(parents=True)
    (source / "hooks").mkdir(parents=True)
    (source / "webhooks").mkdir(parents=True)
    (source / "bindings").mkdir(parents=True)
    (source / "credentials").mkdir(parents=True)
    (source / "devices").mkdir(parents=True)
    (source / "identity").mkdir(parents=True)
    (source / "memory").mkdir(parents=True)
    (source / "agents" / "main" / "agent").mkdir(parents=True)

    (workspace / "SOUL.md").write_text("Operate calmly.\n", encoding="utf-8")
    (workspace / "AGENTS.md").write_text("Use repo-local tools first.\n", encoding="utf-8")
    (workspace / "USER.md").write_text("Prefers concise Chinese reports.\n", encoding="utf-8")
    (workspace / "MEMORY.md").write_text("Main memory line.\n", encoding="utf-8")
    (workspace / "IDENTITY.md").write_text("Legacy identity overlay.\n", encoding="utf-8")
    (workspace / "TOOLS.md").write_text("Legacy tool policy.\n", encoding="utf-8")
    (workspace / "HEARTBEAT.md").write_text("Legacy heartbeat.\n", encoding="utf-8")
    (workspace / "BOOTSTRAP.md").write_text("Legacy bootstrap.\n", encoding="utf-8")
    (workspace / "hooks" / "before_prompt.js").write_text(
        "export default function beforePrompt() {}\n",
        encoding="utf-8",
    )
    (workspace / "memory" / "2026-05-11.md").write_text(
        "Daily operations note.\n",
        encoding="utf-8",
    )
    (workspace / "skills" / "triage" / "SKILL.md").write_text(
        "---\nname: triage\ndescription: Triage production incidents.\n---\n"
        "Check impact before mitigation.\n",
        encoding="utf-8",
    )
    (workspace / ".agents" / "skills" / "workspace-local" / "SKILL.md").write_text(
        "---\nname: workspace-local\ndescription: Workspace local skill.\n---\n",
        encoding="utf-8",
    )
    (source / "skills" / "research" / "SKILL.md").write_text(
        "---\nname: research\ndescription: Source-level research skill.\n---\n",
        encoding="utf-8",
    )
    (workspace / "tts" / "voices" / "ops.txt").write_text(
        "voice preset\n",
        encoding="utf-8",
    )
    (source / "workspace.default" / "SOUL.md").write_text(
        "Default workspace soul should not win explicit workspace.\n",
        encoding="utf-8",
    )
    (source / "extensions" / "legacy-plugin" / "manifest.json").write_text(
        json.dumps({"id": "legacy-plugin", "kind": "extension"}),
        encoding="utf-8",
    )
    (source / "cron" / "store.json").write_text(
        json.dumps({"jobs": [{"id": "stored-nightly"}]}),
        encoding="utf-8",
    )
    (source / "hooks" / "gateway-start.js").write_text(
        "export default function gatewayStart() {}\n",
        encoding="utf-8",
    )
    (source / "webhooks" / "incoming.json").write_text(
        json.dumps({"route": "/legacy"}),
        encoding="utf-8",
    )
    (source / "bindings" / "discord.json").write_text(
        json.dumps({"channel": "discord-channel-1"}),
        encoding="utf-8",
    )
    (source / "credentials" / "telegram-default-allowFrom.json").write_text(
        json.dumps({"allow": ["123"]}),
        encoding="utf-8",
    )
    (source / "devices" / "device.json").write_text(
        json.dumps({"id": "device-1"}),
        encoding="utf-8",
    )
    (source / "identity" / "profile.json").write_text(
        json.dumps({"name": "legacy"}),
        encoding="utf-8",
    )
    (source / "memory" / "main.sqlite").write_bytes(b"SQLite format 3\x00")
    (source / "workspace.zip").write_bytes(b"not a real zip")
    (source / "agents" / "main" / "agent" / "auth-profiles.json").write_text(
        json.dumps({"anthropic": {"token": "do-not-copy"}}),
        encoding="utf-8",
    )
    (source / "exec-approvals.json").write_text(
        json.dumps({"allow": ["^git status$", "^uv run pytest "]}),
        encoding="utf-8",
    )
    (source / ".env").write_text(
        "\n".join(
            [
                "ANTHROPIC_API_KEY=sk-ant-realistic",
                "TELEGRAM_BOT_TOKEN=telegram-secret-token",
                "DISCORD_BOT_TOKEN=discord-secret-token",
                "SLACK_BOT_TOKEN=xoxb-slack-secret-token",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    config = {
                "agents": {
                    "defaults": {
                        "workspace": str(workspace),
                        "model": "claude-3-5-sonnet-latest",
                        "timeoutSeconds": 900,
                        "verboseDefault": True,
                        "thinkingDefault": "medium",
                        "compaction": {"mode": "auto", "model": "claude-haiku"},
                        "humanDelay": {"minMs": 100, "maxMs": 500},
                        "userTimezone": "Asia/Shanghai",
                    }
                },
                "models": {
                    "providers": {
                        "anthropic": {
                            "baseUrl": "https://anthropic.example.test/v1",
                        }
                    },
                    "aliases": {"ops": "claude-3-5-sonnet-latest"},
                },
                "mcp": {
                    "servers": {
                        "filesystem": {
                            "command": "npx",
                            "args": ["-y", "@modelcontextprotocol/server-filesystem", "."],
                            "env": {"NODE_ENV": "test"},
                        },
                        "docs": {
                            "url": "http://127.0.0.1:8765/sse",
                            "headers": {"X-Test": "openclaw"},
                        },
                    }
                },
                "messages": {
                    "telegram": {"defaultChatId": "telegram-chat-1"},
                    "discord": {"defaultChannelId": "discord-channel-1"},
                    "whatsapp": {"allowedUsers": ["15551234567"]},
                    "signal": {"account": "+15550000000", "allowedUsers": ["+15551111111"]},
                    "tts": {"provider": "elevenlabs", "voice": "ops-voice"},
                },
                "tools": {"exec": {"timeoutSec": 30}, "web": {"enabled": True}},
                "plugins": {"enabled": True, "entries": [{"id": "legacy-plugin"}]},
                "gateway": {"port": 3000},
                "cron": {"jobs": [{"id": "legacy-nightly"}]},
                "hooks": {"beforePrompt": ["./hooks/before_prompt.js"]},
                "session": {"resetTriggers": ["done"], "sendPolicy": "thread-bound"},
                "browser": {"cdpUrl": "http://127.0.0.1:9222", "headless": True},
                "approvals": {"mode": "ask"},
                "memory": {"backend": "qmd", "vector": {"enabled": True}},
                "skills": {"enabled": {"triage": True}, "env": {"triage": {"A": "B"}}},
                "ui": {"theme": "dark", "identity": "ops"},
                "logging": {"level": "debug"},
                "diagnostics": {"otel": True},
            }
    (source / "openclaw.json").write_text(
        json.dumps(
            config,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (source / "clawdbot.json").write_text(
        json.dumps({"legacy": "alias-config"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (source / "moltbot.json").write_text(
        json.dumps({"legacy": "older-alias-config"}, ensure_ascii=False),
        encoding="utf-8",
    )
    return source


def _write_existing_opensquilla_config(config_path: Path, home: Path) -> None:
    cfg = GatewayConfig(
        host="127.0.0.9",
        port=19999,
        auth=AuthConfig(mode="token", token="keep-auth-token"),
        rate_limit=RateLimitConfig(max_requests=77, window_seconds=11),
        safety=SafetyConfig(injection_scan_mode="enforce"),
        task_runtime=TaskRuntimeConfig(max_concurrency=2, max_pending_per_session=9),
        search_provider="brave",
        agents=[
            AgentEntryConfig(
                id="ops",
                name="Operations",
                workspace=str(home / "existing-agent-workspace"),
            )
        ],
    )
    persist_config(cfg, path=config_path, backup=False)


def test_realistic_cli_apply_is_isolated_and_preserves_unrelated_config(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = _write_realistic_openclaw_home(tmp_path)
    home = tmp_path / "isolated-opensquilla-home"
    config_path = tmp_path / "opensquilla.toml"
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(home))
    _write_existing_opensquilla_config(config_path, home)

    existing_skill = home / "skills" / "openclaw-imports" / "triage" / "SKILL.md"
    existing_skill.parent.mkdir(parents=True)
    existing_skill.write_text("existing skill stays\n", encoding="utf-8")
    unrelated_workspace_file = home / "workspace" / "LOCAL_ONLY.md"
    unrelated_workspace_file.parent.mkdir(parents=True)
    unrelated_workspace_file.write_text("do not touch\n", encoding="utf-8")
    unrelated_state_file = home / "state" / "sessions" / "keep.txt"
    unrelated_state_file.parent.mkdir(parents=True)
    unrelated_state_file.write_text("session state\n", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "migrate",
            "openclaw",
            "--source",
            str(source),
            "--config",
            str(config_path),
            "--apply",
            "--migrate-secrets",
            "--skill-conflict",
            "rename",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    report = json.loads(result.stdout)
    encoded_report = json.dumps(report)
    assert "sk-ant-realistic" not in encoded_report
    assert "telegram-secret-token" not in encoded_report
    assert "discord-secret-token" not in encoded_report
    assert "xoxb-slack-secret-token" not in encoded_report

    config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert config["auth"]["mode"] == "token"
    assert config["auth"]["token"] == "keep-auth-token"
    assert config["rate_limit"]["max_requests"] == 77
    assert config["rate_limit"]["window_seconds"] == 11
    assert config["safety"]["injection_scan_mode"] == "enforce"
    assert config["task_runtime"]["max_concurrency"] == 2
    assert config["task_runtime"]["max_pending_per_session"] == 9
    assert config["search_provider"] == "brave"
    assert config["agents"][0]["id"] == "ops"

    assert config["llm"]["provider"] == "anthropic"
    assert config["llm"]["model"] == "claude-3-5-sonnet-latest"
    assert config["llm"]["api_key_env"] == "ANTHROPIC_API_KEY"
    assert config["llm"]["base_url"] == "https://anthropic.example.test/v1"
    assert config["agent_runtime_timeout_seconds"] == 900
    assert config["mcp"]["enabled"] is True
    assert {entry["name"] for entry in config["mcp"]["servers"]} == {
        "filesystem",
        "docs",
    }
    assert str(home / "skills" / "openclaw-imports") in config["skills"]["extra_dirs"]

    channels = {entry["type"]: entry for entry in config["channels"]["channels"]}
    assert channels["telegram"]["token"] == "telegram-secret-token"
    assert channels["telegram"]["default_chat_id"] == "telegram-chat-1"
    assert channels["discord"]["token"] == "discord-secret-token"
    assert channels["discord"]["default_channel_id"] == "discord-channel-1"
    assert channels["slack"]["token"] == "xoxb-slack-secret-token"

    env_text = (home / ".env").read_text(encoding="utf-8")
    assert "ANTHROPIC_API_KEY=sk-ant-realistic" in env_text
    assert "OPENSQUILLA_SAFE_BIN_ALLOW=^git status$,^uv run pytest " in env_text
    assert existing_skill.read_text(encoding="utf-8") == "existing skill stays\n"
    renamed_skill = home / "skills" / "openclaw-imports" / "triage-imported-1" / "SKILL.md"
    assert "Triage production incidents" in renamed_skill.read_text(encoding="utf-8")
    source_skill = home / "skills" / "openclaw-imports" / "research" / "SKILL.md"
    assert "Source-level research skill" in source_skill.read_text(encoding="utf-8")
    workspace_agent_skill = (
        home / "skills" / "openclaw-imports" / "workspace-local" / "SKILL.md"
    )
    assert "Workspace local skill" in workspace_agent_skill.read_text(encoding="utf-8")
    assert unrelated_workspace_file.read_text(encoding="utf-8") == "do not touch\n"
    assert unrelated_state_file.read_text(encoding="utf-8") == "session state\n"

    workspace = home / "workspace"
    assert (workspace / "SOUL.md").read_text(encoding="utf-8") == "Operate calmly.\n"
    assert "Daily operations note." in (workspace / "MEMORY.md").read_text(
        encoding="utf-8"
    )
    assert (home / "tts" / "voices" / "ops.txt").read_text(encoding="utf-8") == (
        "voice preset\n"
    )

    output_dir = Path(report["output_dir"])
    assert (output_dir / "report.json").is_file()
    assert (output_dir / "summary.md").is_file()
    assert (output_dir / "archive" / "plugins-config.json").is_file()
    assert (output_dir / "archive" / "gateway-config.json").is_file()
    assert (output_dir / "archive" / "cron-config.json").is_file()
    assert (output_dir / "archive" / "hooks-config.json").is_file()
    assert (output_dir / "archive" / "session-config.json").is_file()
    assert (output_dir / "archive" / "browser-config.json").is_file()
    assert (output_dir / "archive" / "approvals-config.json").is_file()
    assert (output_dir / "archive" / "memory-backend-config.json").is_file()
    assert (output_dir / "archive" / "skills-registry-config.json").is_file()
    assert (output_dir / "archive" / "ui-identity-config.json").is_file()
    logging_archive = json.loads(
        (output_dir / "archive" / "logging-config.json").read_text(encoding="utf-8")
    )
    assert logging_archive["logging"]["level"] == "debug"
    assert logging_archive["diagnostics"]["otel"] is True
    assert (output_dir / "archive" / "tts-config.json").is_file()
    assert (output_dir / "archive" / "files" / "workspace" / "IDENTITY.md").is_file()
    assert (output_dir / "archive" / "files" / "workspace" / "TOOLS.md").is_file()
    assert (output_dir / "archive" / "files" / "workspace" / "HEARTBEAT.md").is_file()
    assert (output_dir / "archive" / "files" / "workspace" / "BOOTSTRAP.md").is_file()
    assert (
        output_dir / "archive" / "files" / "workspace" / "hooks" / "before_prompt.js"
    ).is_file()
    assert (
        output_dir / "archive" / "files" / "extensions" / "legacy-plugin" / "manifest.json"
    ).is_file()
    assert (output_dir / "archive" / "files" / "cron" / "store.json").is_file()
    assert (output_dir / "archive" / "files" / "hooks" / "gateway-start.js").is_file()
    assert (output_dir / "archive" / "files" / "webhooks" / "incoming.json").is_file()
    assert (output_dir / "archive" / "files" / "bindings" / "discord.json").is_file()
    assert not (output_dir / "archive" / "files" / "credentials").exists()
    assert not (output_dir / "archive" / "files" / "devices").exists()
    assert not (output_dir / "archive" / "files" / "identity").exists()
    assert not (output_dir / "archive" / "files" / "workspace.zip").exists()
    assert not (output_dir / "archive" / "files" / "memory" / "main.sqlite").exists()

    item_statuses = {(item["kind"], item["status"]) for item in report["items"]}
    assert ("credentials", "skipped") in item_statuses
    assert ("devices", "skipped") in item_statuses
    assert ("identity", "skipped") in item_statuses
    assert ("workspace.zip", "skipped") in item_statuses
    assert ("memory/main.sqlite", "skipped") in item_statuses


def test_realistic_cli_dry_run_does_not_write_isolated_targets(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = _write_realistic_openclaw_home(tmp_path)
    home = tmp_path / "isolated-opensquilla-home"
    config_path = tmp_path / "opensquilla.toml"
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(home))

    result = runner.invoke(
        app,
        [
            "migrate",
            "openclaw",
            "--source",
            str(source),
            "--config",
            str(config_path),
            "--migrate-secrets",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    report = json.loads(result.stdout)
    assert report["apply"] is False
    assert any(item["status"] == "planned" for item in report["items"])
    assert not config_path.exists()
    assert not (home / ".env").exists()
    assert not (home / "workspace").exists()
    assert not (home / "skills" / "openclaw-imports").exists()
