"""Hermes Agent to OpenSquilla migration."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import yaml

from opensquilla.gateway.config import ChannelsConfig, GatewayConfig, MCPServerEntry
from opensquilla.onboarding.config_store import load_config, persist_config
from opensquilla.paths import default_opensquilla_home

SKILL_IMPORT_DIRNAME = "hermes-imports"
SECRET_REDACTION = "[redacted]"
SKILL_CONFLICT_MODES = {"skip", "overwrite", "rename"}
MAX_SKILL_FILE_BYTES = 256_000
MAX_MEMORY_CHARS = 80_000
MEMORY_OVERFLOW_DIR = "memory-overflow"

USER_DATA_OPTIONS = {"soul", "memory", "user-profile", "skills", "workspace-files"}
RUNTIME_CONFIG_OPTIONS = {
    "model-config",
    "provider-keys",
    "search-config",
    "telegram-settings",
    "discord-settings",
    "slack-settings",
    "mcp-servers",
    "tools-config",
    "archive",
    "browser-config",
    "session-config",
    "cron-jobs",
    "plugins-config",
    "gateway-config",
    "memory-backend",
    "approvals-config",
    "logging-config",
}
MIGRATION_OPTIONS = USER_DATA_OPTIONS | RUNTIME_CONFIG_OPTIONS
MIGRATION_PRESETS = {"user-data": USER_DATA_OPTIONS, "full": MIGRATION_OPTIONS}

SECRET_ENV_KEYS = {
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "ANTHROPIC_API_KEY",
    "BRAVE_API_KEY",
    "BRAVE_SEARCH_API_KEY",
    "TAVILY_API_KEY",
    "TELEGRAM_BOT_TOKEN",
    "DISCORD_BOT_TOKEN",
    "SLACK_BOT_TOKEN",
    "SLACK_APP_TOKEN",
}

NON_SECRET_ENV_KEYS = {
    "OPENAI_BASE_URL",
    "OPENROUTER_BASE_URL",
    "ANTHROPIC_BASE_URL",
}

PROVIDER_ENV_KEYS = {
    "openrouter": "OPENROUTER_API_KEY",
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}

ARCHIVE_SOURCE_ARTIFACTS = {"cron": "cron-jobs", "plugins": "plugins-config"}
SKIP_SOURCE_ARTIFACTS = {
    "state.db",
    "state.db-wal",
    "state.db-shm",
    "kanban.db",
    "sessions",
    "logs",
    "auth.json",
    "checkpoints",
    "cache",
}


@dataclass(frozen=True)
class HermesMigrationOptions:
    source: Path | str | None = None
    profile: str | None = None
    config_path: Path | str | None = None
    apply: bool = False
    migrate_secrets: bool = False
    overwrite: bool = False
    preset: str = "full"
    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    skill_conflict: Literal["skip", "overwrite", "rename"] = "skip"


@dataclass
class ItemResult:
    kind: str
    source: str | None
    destination: str | None
    status: str
    reason: str = ""
    details: dict[str, Any] = field(default_factory=dict)


def _as_path(value: Path | str | None) -> Path | None:
    if value is None:
        return None
    return Path(value).expanduser()


def _is_valid_hermes_home(path: Path) -> bool:
    return any(
        (path / name).exists()
        for name in ("config.yaml", ".env", "SOUL.md", "memories", "skills")
    )


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8-sig")) or {}
    return data if isinstance(data, dict) else {}


def _load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


class HermesMigrator:
    def __init__(self, options: HermesMigrationOptions) -> None:
        self.options = options
        self.source = self._resolve_source()
        self.home = default_opensquilla_home()
        timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
        self.output_dir = self.home / "migration" / "hermes" / timestamp
        self.items: list[ItemResult] = []
        self.config_path = _as_path(options.config_path)
        self._config_obj: GatewayConfig | None = None
        self._config_changed = False
        self._env_additions: dict[str, str] = {}

    def _resolve_source(self) -> Path:
        explicit = _as_path(self.options.source)
        if explicit is not None:
            return explicit

        env_home = os.environ.get("HERMES_HOME")
        root = Path(env_home).expanduser() if env_home else Path.home() / ".hermes"
        if self.options.profile:
            return root / "profiles" / self.options.profile
        return root

    def migrate(self) -> dict[str, Any]:
        if not _is_valid_hermes_home(self.source):
            self._record("source", self.source, None, "error", "not a Hermes home")
            return self._report()
        selected = self._selected_options()
        self._plan_user_data(selected)
        self._migrate_config_and_env(selected)
        self._write_config()
        self._write_env()
        self._archive_unsupported(selected)
        self._write_reports()
        return self._report()

    def _config(self) -> GatewayConfig:
        if self._config_obj is None:
            self._config_obj = load_config(self.config_path)
        return self._config_obj

    def _selected_options(self) -> set[str]:
        selected = set(MIGRATION_PRESETS.get(self.options.preset, MIGRATION_PRESETS["full"]))
        selected.update(self.options.include)
        selected.difference_update(self.options.exclude)
        return selected

    def _workspace_dir(self) -> Path:
        return self.home / "workspace"

    def _plan_user_data(self, selected: set[str]) -> None:
        if "soul" in selected:
            self._plan_file("soul", self.source / "SOUL.md", self._workspace_dir() / "SOUL.md")
        if "memory" in selected:
            self._plan_file(
                "memory",
                self.source / "memories" / "MEMORY.md",
                self._workspace_dir() / "MEMORY.md",
            )
        if "user-profile" in selected:
            self._plan_file(
                "user-profile",
                self.source / "memories" / "USER.md",
                self._workspace_dir() / "USER.md",
            )
        if "skills" in selected:
            self._plan_skills()

    def _plan_file(self, kind: str, source: Path, destination: Path) -> None:
        if not source.exists():
            self._record(kind, source, destination, "skipped", "source missing")
            return
        status = "migrated" if self.options.apply else "planned"
        if self.options.apply:
            self._write_text_merge(source, destination)
        self._record(
            kind,
            source,
            destination,
            status,
        )

    def _plan_skills(self) -> None:
        skills_dir = self.source / "skills"
        destination_root = self.home / "skills" / SKILL_IMPORT_DIRNAME
        if not skills_dir.exists():
            self._record("skills", skills_dir, destination_root, "skipped", "source missing")
            return
        for skill_dir in sorted(path for path in skills_dir.iterdir() if path.is_dir()):
            target = destination_root / skill_dir.name
            status = "migrated" if self.options.apply else "planned"
            reason = ""
            if self.options.apply:
                copied = self._copy_skill_dir(skill_dir, target)
                if copied is None:
                    status = "skipped"
                    reason = "target exists"
                else:
                    target = copied
            self._record("skills", skill_dir, target, status, reason)

    def _write_text_merge(self, source: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        source_text = source.read_text(encoding="utf-8-sig")
        if destination.exists() and not self.options.overwrite:
            existing = destination.read_text(encoding="utf-8")
            if source_text.strip() in existing:
                return
            destination.write_text(
                existing.rstrip() + "\n\n" + source_text.lstrip(), encoding="utf-8"
            )
            return
        destination.write_text(source_text, encoding="utf-8")

    def _copy_skill_dir(self, source: Path, destination: Path) -> Path | None:
        target = destination
        if target.exists():
            if self.options.skill_conflict == "skip":
                return None
            if self.options.skill_conflict == "rename":
                index = 1
                while target.exists():
                    target = destination.with_name(f"{destination.name}-imported-{index}")
                    index += 1
            elif self.options.skill_conflict == "overwrite":
                shutil.rmtree(target)
        shutil.copytree(source, target)
        return target

    def _write_reports(self) -> None:
        if not self.options.apply:
            return
        self.output_dir.mkdir(parents=True, exist_ok=True)
        report = self._report()
        (self.output_dir / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        counts: dict[str, int] = {}
        for item in report["items"]:
            counts[item["status"]] = counts.get(item["status"], 0) + 1
        lines = ["# Hermes Migration Summary", ""]
        lines.extend(f"- {key}: {value}" for key, value in sorted(counts.items()))
        (self.output_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _migrate_config_and_env(self, selected: set[str]) -> None:
        raw_config = _load_yaml(self.source / "config.yaml")
        env_values = _load_env_file(self.source / ".env")
        if "skills" in selected:
            self._ensure_skills_extra_dir()
        if "model-config" in selected:
            self._migrate_model_config(raw_config)
        if "provider-keys" in selected or "search-config" in selected:
            self._migrate_env_values(env_values)
        if "mcp-servers" in selected:
            self._migrate_mcp_servers(raw_config)
        self._migrate_channels(raw_config, env_values, selected)

    def _migrate_model_config(self, raw_config: dict[str, Any]) -> None:
        raw_model = raw_config.get("model")
        model_cfg = raw_model if isinstance(raw_model, dict) else {}
        provider = str(model_cfg.get("provider") or "").strip()
        model = str(model_cfg.get("model") or model_cfg.get("default") or "").strip()
        if not provider and not model:
            self._record("model-config", self.source / "config.yaml", self.config_path, "skipped")
            return
        cfg = self._config()
        base_url = model_cfg.get("base_url") or model_cfg.get("baseUrl")
        target_provider = "openai" if provider == "custom" and base_url else provider
        if provider:
            cfg.llm.provider = target_provider
            cfg.llm.api_key_env = PROVIDER_ENV_KEYS.get(
                target_provider, cfg.llm.api_key_env
            )
        if model:
            cfg.llm.model = model
        if base_url:
            cfg.llm.base_url = str(base_url)
        self._config_changed = True
        self._record(
            "model-config",
            self.source / "config.yaml",
            self.config_path,
            "migrated" if self.options.apply else "planned",
        )

    def _migrate_env_values(self, env_values: dict[str, str]) -> None:
        migrated = 0
        for key, value in env_values.items():
            target_key = "BRAVE_SEARCH_API_KEY" if key == "BRAVE_API_KEY" else key
            if target_key not in SECRET_ENV_KEYS and target_key not in NON_SECRET_ENV_KEYS:
                continue
            if not value:
                continue
            is_secret = target_key in SECRET_ENV_KEYS
            if is_secret and not self.options.migrate_secrets:
                continue
            self._env_additions[target_key] = value
            migrated += 1
            if target_key == "BRAVE_SEARCH_API_KEY":
                cfg = self._config()
                cfg.search_provider = "brave"
                cfg.search_api_key_env = "BRAVE_SEARCH_API_KEY"
                self._config_changed = True
        self._record(
            "provider-keys",
            self.source / ".env",
            self.home / ".env",
            "migrated" if migrated and self.options.apply else "planned" if migrated else "skipped",
            (
                "pass --migrate-secrets to migrate recognized secrets"
                if any(key in SECRET_ENV_KEYS for key in env_values)
                and not self.options.migrate_secrets
                else ""
            ),
            {"migrated_keys": [SECRET_REDACTION] * migrated},
        )

    def _ensure_skills_extra_dir(self) -> None:
        destination_root = str(self.home / "skills" / SKILL_IMPORT_DIRNAME)
        cfg = self._config()
        extra_dirs = list(cfg.skills.extra_dirs)
        if destination_root not in extra_dirs:
            extra_dirs.append(destination_root)
            cfg.skills.extra_dirs = extra_dirs
            self._config_changed = True
            self._record(
                "skills-config",
                self.source / "skills",
                self.config_path,
                "migrated" if self.options.apply else "planned",
            )

    def _migrate_mcp_servers(self, raw_config: dict[str, Any]) -> None:
        raw_mcp = raw_config.get("mcp")
        servers = raw_mcp.get("servers", {}) if isinstance(raw_mcp, dict) else {}
        if not isinstance(servers, dict) or not servers:
            self._record("mcp-servers", self.source / "config.yaml", self.config_path, "skipped")
            return
        entries: list[MCPServerEntry] = []
        for name, raw in servers.items():
            if not isinstance(raw, dict):
                continue
            entry: dict[str, Any] = {"name": name}
            for key in ("command", "args", "env", "url"):
                if key in raw:
                    entry[key] = raw[key]
            if entry.get("url") and not entry.get("command"):
                entry["transport"] = "sse"
            elif entry.get("command"):
                entry["transport"] = "stdio"
            entries.append(MCPServerEntry.model_validate(entry))
        cfg = self._config()
        cfg.mcp.enabled = True
        cfg.mcp.servers = entries
        self._config_changed = True
        self._record(
            "mcp-servers",
            self.source / "config.yaml",
            self.config_path,
            "migrated" if self.options.apply else "planned",
        )

    def _migrate_channels(
        self,
        raw_config: dict[str, Any],
        env_values: dict[str, str],
        selected: set[str],
    ) -> None:
        if not self.options.migrate_secrets:
            self._record(
                "channels",
                self.source / ".env",
                self.config_path,
                "skipped",
                "pass --migrate-secrets to migrate channel tokens",
            )
            return
        raw_entries = [
            entry.model_dump(mode="python") for entry in self._config().channels.channels
        ]
        changed = False

        def upsert(entry: dict[str, Any]) -> None:
            nonlocal changed
            for idx, existing in enumerate(raw_entries):
                if existing.get("name") == entry["name"]:
                    raw_entries[idx] = entry
                    changed = True
                    return
            raw_entries.append(entry)
            changed = True

        if "telegram-settings" in selected and env_values.get("TELEGRAM_BOT_TOKEN"):
            telegram = raw_config.get("telegram", {})
            telegram_cfg = telegram if isinstance(telegram, dict) else {}
            upsert(
                {
                    "name": "hermes-telegram",
                    "type": "telegram",
                    "token": env_values["TELEGRAM_BOT_TOKEN"],
                    "default_chat_id": str(telegram_cfg.get("default_chat_id", "")),
                }
            )
        if "discord-settings" in selected and env_values.get("DISCORD_BOT_TOKEN"):
            discord = raw_config.get("discord", {})
            discord_cfg = discord if isinstance(discord, dict) else {}
            upsert(
                {
                    "name": "hermes-discord",
                    "type": "discord",
                    "token": env_values["DISCORD_BOT_TOKEN"],
                    "default_channel_id": str(discord_cfg.get("default_channel_id", "")),
                }
            )
        if "slack-settings" in selected and env_values.get("SLACK_BOT_TOKEN"):
            slack = raw_config.get("slack", {})
            slack_cfg = slack if isinstance(slack, dict) else {}
            upsert(
                {
                    "name": "hermes-slack",
                    "type": "slack",
                    "token": env_values["SLACK_BOT_TOKEN"],
                    "slack_channel_id": str(slack_cfg.get("channel_id", "")),
                }
            )
        if changed:
            cfg = self._config()
            cfg.channels = ChannelsConfig.model_validate({"channels": raw_entries})
            self._config_changed = True
            self._record(
                "channels",
                self.source / ".env",
                self.config_path,
                "migrated" if self.options.apply else "planned",
            )

    def _write_env(self) -> None:
        if not self.options.apply or not self._env_additions:
            return
        env_path = self.home / ".env"
        env_path.parent.mkdir(parents=True, exist_ok=True)
        existing = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
        lines = [existing.rstrip()] if existing.strip() else []
        lines.extend(f"{key}={value}" for key, value in sorted(self._env_additions.items()))
        env_path.write_text("\n".join(line for line in lines if line) + "\n", encoding="utf-8")

    def _write_config(self) -> None:
        if self.options.apply and self._config_changed and self._config_obj is not None:
            persist_config(self._config_obj, path=self.config_path, backup=True)

    def _archive_unsupported(self, selected: set[str]) -> None:
        if "archive" not in selected:
            return
        for name, kind in ARCHIVE_SOURCE_ARTIFACTS.items():
            source = self.source / name
            if not source.exists():
                continue
            destination = self.output_dir / "archive" / "files" / name
            if self.options.apply:
                destination.parent.mkdir(parents=True, exist_ok=True)
                if source.is_dir():
                    shutil.copytree(source, destination, dirs_exist_ok=True)
                else:
                    shutil.copy2(source, destination)
            self._record(
                kind,
                source,
                destination,
                "archived" if self.options.apply else "planned",
            )
        for name in sorted(SKIP_SOURCE_ARTIFACTS):
            source = self.source / name
            if source.exists():
                self._record(
                    name,
                    source,
                    None,
                    "skipped",
                    "runtime or credential artifact is not imported",
                )

    def _record(
        self,
        kind: str,
        source: Path | str | None,
        destination: Path | str | None,
        status: str,
        reason: str = "",
        details: dict[str, Any] | None = None,
    ) -> None:
        self.items.append(
            ItemResult(
                kind=kind,
                source=str(source) if source is not None else None,
                destination=str(destination) if destination is not None else None,
                status=status,
                reason=reason,
                details=details or {},
            )
        )

    def _report(self) -> dict[str, Any]:
        return {
            "source": str(self.source),
            "target_home": str(self.home),
            "output_dir": str(self.output_dir),
            "apply": self.options.apply,
            "items": [asdict(item) for item in self.items],
        }
