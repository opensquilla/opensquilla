# Hermes Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `opensquilla migrate hermes` so Hermes Agent homes can be dry-run, applied, reported, and safely migrated into OpenSquilla-native config, workspace, env, and skill locations.

**Architecture:** Implement a native `HermesMigrator` modeled after `OpenClawMigrator`, with Hermes-specific source detection and mapping logic. Keep the first version focused on config, env, persona, memory, skills, provider keys, supported channels, MCP, tool policy, and unsupported artifact archival; exclude live runtime/session import.

**Tech Stack:** Python 3.12, Typer, Pydantic config models, PyYAML, tomli-w via existing config store, pytest, existing OpenSquilla migration helpers and tests.

---

## File Map

- Create: `src/opensquilla/migration/hermes.py`
  - Owns Hermes source detection, selected-option resolution, dry-run planning, apply writes, report generation, redaction, archive handling, and config/env/workspace/skills mapping.
- Modify: `src/opensquilla/cli/migrate_cmd.py`
  - Adds `opensquilla migrate hermes` and Hermes-specific option validation.
- Create: `tests/test_migration/test_hermes_migration.py`
  - Focused unit/integration tests for source detection, dry-run, apply, env/secrets, config, memory, skills, conflicts, and archives.
- Create: `tests/test_migration/test_hermes_e2e.py`
  - Realistic CLI test using a synthetic Hermes home and existing OpenSquilla config.
- Existing reference files:
  - `src/opensquilla/migration/openclaw.py`
  - `tests/test_migration/test_openclaw_migration.py`
  - `tests/test_migration/test_openclaw_e2e.py`
  - `src/opensquilla/gateway/config.py`
  - `src/opensquilla/onboarding/config_store.py`
  - `src/opensquilla/paths.py`

## Migration Options

Hermes migration option ids:

```python
USER_DATA_OPTIONS = {
    "soul",
    "memory",
    "user-profile",
    "skills",
    "workspace-files",
}

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
```

`user-data` preset uses `USER_DATA_OPTIONS`. `full` uses all options.

## Task 1: Add Hermes Migrator Skeleton and Source Detection

**Files:**
- Create: `src/opensquilla/migration/hermes.py`
- Test: `tests/test_migration/test_hermes_migration.py`

- [ ] **Step 1: Write failing source-detection tests**

Add this test file:

```python
from __future__ import annotations

import os
from pathlib import Path

import pytest

from opensquilla.migration.hermes import HermesMigrationOptions, HermesMigrator


def _make_hermes_home(root: Path) -> Path:
    home = root / ".hermes"
    home.mkdir()
    (home / "config.yaml").write_text("model:\n  provider: openrouter\n", encoding="utf-8")
    return home


def test_source_detection_prefers_explicit_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    explicit = _make_hermes_home(tmp_path / "explicit")
    env_home = _make_hermes_home(tmp_path / "env")
    monkeypatch.setenv("HERMES_HOME", str(env_home))

    migrator = HermesMigrator(HermesMigrationOptions(source=explicit))

    assert migrator.source == explicit


def test_source_detection_uses_hermes_home_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_home = _make_hermes_home(tmp_path / "env")
    monkeypatch.setenv("HERMES_HOME", str(env_home))

    migrator = HermesMigrator(HermesMigrationOptions())

    assert migrator.source == env_home


def test_source_detection_uses_profile_under_root_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _make_hermes_home(tmp_path)
    profile = root / "profiles" / "work"
    profile.mkdir(parents=True)
    (profile / "config.yaml").write_text("model:\n  provider: anthropic\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(root))

    migrator = HermesMigrator(HermesMigrationOptions(profile="work"))

    assert migrator.source == profile
```

- [ ] **Step 2: Run tests and verify import failure**

Run:

```bash
uv run pytest tests/test_migration/test_hermes_migration.py -q
```

Expected: fail because `opensquilla.migration.hermes` does not exist.

- [ ] **Step 3: Implement skeleton**

Create `src/opensquilla/migration/hermes.py` with:

```python
"""Hermes Agent to OpenSquilla migration."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import yaml

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


class HermesMigrator:
    def __init__(self, options: HermesMigrationOptions) -> None:
        self.options = options
        self.source = self._resolve_source()
        self.home = default_opensquilla_home()
        self.output_dir = self.home / "migration" / "hermes" / datetime.utcnow().strftime(
            "%Y%m%d-%H%M%S"
        )
        self.items: list[ItemResult] = []

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
```

- [ ] **Step 4: Run source-detection tests**

Run:

```bash
uv run pytest tests/test_migration/test_hermes_migration.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/opensquilla/migration/hermes.py tests/test_migration/test_hermes_migration.py
git commit -m "Add Hermes migration skeleton"
```

## Task 2: Add Dry-Run Planning for Core User Data

**Files:**
- Modify: `src/opensquilla/migration/hermes.py`
- Modify: `tests/test_migration/test_hermes_migration.py`

- [ ] **Step 1: Add dry-run test**

Append:

```python
def test_dry_run_plans_user_data_without_writes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
```

- [ ] **Step 2: Run test and verify failure**

```bash
uv run pytest tests/test_migration/test_hermes_migration.py::test_dry_run_plans_user_data_without_writes -q
```

Expected: fail because planning methods do not exist.

- [ ] **Step 3: Implement planning helpers**

Add imports:

```python
import shutil
```

Add methods inside `HermesMigrator` and call them from `migrate()` after source validation:

```python
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
        self._record(
            kind,
            source,
            destination,
            "migrated" if self.options.apply else "planned",
        )

    def _plan_skills(self) -> None:
        skills_dir = self.source / "skills"
        destination_root = self.home / "skills" / SKILL_IMPORT_DIRNAME
        if not skills_dir.exists():
            self._record("skills", skills_dir, destination_root, "skipped", "source missing")
            return
        for skill_dir in sorted(path for path in skills_dir.iterdir() if path.is_dir()):
            self._record(
                "skills",
                skill_dir,
                destination_root / skill_dir.name,
                "migrated" if self.options.apply else "planned",
            )
```

Change `migrate()`:

```python
    def migrate(self) -> dict[str, Any]:
        if not _is_valid_hermes_home(self.source):
            self._record("source", self.source, None, "error", "not a Hermes home")
            return self._report()
        selected = self._selected_options()
        self._plan_user_data(selected)
        return self._report()
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_migration/test_hermes_migration.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/opensquilla/migration/hermes.py tests/test_migration/test_hermes_migration.py
git commit -m "Plan Hermes user data migration"
```

## Task 3: Apply Persona, Memory, User Profile, and Skills

**Files:**
- Modify: `src/opensquilla/migration/hermes.py`
- Modify: `tests/test_migration/test_hermes_migration.py`

- [ ] **Step 1: Add apply test**

Append:

```python
def test_apply_migrates_user_data_and_skills(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = _make_hermes_home(tmp_path)
    (source / "SOUL.md").write_text("Hermes soul\n", encoding="utf-8")
    memories = source / "memories"
    memories.mkdir()
    (memories / "MEMORY.md").write_text("memory line\n", encoding="utf-8")
    (memories / "USER.md").write_text("user profile\n", encoding="utf-8")
    skill = source / "skills" / "demo"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: demo\ndescription: Demo\n---\nBody\n", encoding="utf-8")
    home = tmp_path / "opensquilla-home"
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(home))

    report = HermesMigrator(HermesMigrationOptions(source=source, apply=True)).migrate()

    assert (home / "workspace" / "SOUL.md").read_text(encoding="utf-8") == "Hermes soul\n"
    assert "memory line" in (home / "workspace" / "MEMORY.md").read_text(encoding="utf-8")
    assert (home / "workspace" / "USER.md").read_text(encoding="utf-8") == "user profile\n"
    assert (home / "skills" / "hermes-imports" / "demo" / "SKILL.md").is_file()
    assert (Path(report["output_dir"]) / "report.json").is_file()
    assert (Path(report["output_dir"]) / "summary.md").is_file()
```

- [ ] **Step 2: Run test and verify failure**

```bash
uv run pytest tests/test_migration/test_hermes_migration.py::test_apply_migrates_user_data_and_skills -q
```

Expected: fail because apply writes and reports are missing.

- [ ] **Step 3: Implement writes, merge, reports, and skill conflict modes**

Add helpers:

```python
    def _write_text_merge(self, source: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        source_text = source.read_text(encoding="utf-8-sig")
        if destination.exists() and not self.options.overwrite:
            existing = destination.read_text(encoding="utf-8")
            if source_text.strip() in existing:
                return
            destination.write_text(existing.rstrip() + "\n\n" + source_text.lstrip(), encoding="utf-8")
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
```

Update `_plan_file()`:

```python
        status = "migrated" if self.options.apply else "planned"
        if self.options.apply:
            self._write_text_merge(source, destination)
        self._record(kind, source, destination, status)
```

Update `_plan_skills()` loop:

```python
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
```

Call `_write_reports()` before returning from `migrate()`.

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_migration/test_hermes_migration.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/opensquilla/migration/hermes.py tests/test_migration/test_hermes_migration.py
git commit -m "Apply Hermes user data migration"
```

## Task 4: Map Hermes Config, Env, Provider Keys, Search, Channels, and MCP

**Files:**
- Modify: `src/opensquilla/migration/hermes.py`
- Modify: `tests/test_migration/test_hermes_migration.py`

- [ ] **Step 1: Add config/env test**

Append:

```python
import tomllib


def test_apply_maps_config_env_channels_and_mcp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
    assert "BRAVE_SEARCH_API_KEY=brave-secret" in (home / ".env").read_text(encoding="utf-8")
```

- [ ] **Step 2: Run test and verify failure**

```bash
uv run pytest tests/test_migration/test_hermes_migration.py::test_apply_maps_config_env_channels_and_mcp -q
```

Expected: fail because config/env mapping is missing.

- [ ] **Step 3: Implement config/env mapping**

Add imports:

```python
from opensquilla.gateway.config import ChannelsConfig, GatewayConfig, MCPServerEntry
from opensquilla.onboarding.config_store import load_config, persist_config
```

Add constants:

```python
SECRET_ENV_KEYS = {
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "OPENROUTER_BASE_URL",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_BASE_URL",
    "BRAVE_API_KEY",
    "BRAVE_SEARCH_API_KEY",
    "TAVILY_API_KEY",
    "TELEGRAM_BOT_TOKEN",
    "DISCORD_BOT_TOKEN",
    "SLACK_BOT_TOKEN",
    "SLACK_APP_TOKEN",
}

PROVIDER_ENV_KEYS = {
    "openrouter": "OPENROUTER_API_KEY",
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}
```

Add helpers:

```python
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
```

Inside `HermesMigrator.__init__`:

```python
        self.config_path = _as_path(options.config_path)
        self._config_obj: GatewayConfig | None = None
        self._config_changed = False
        self._env_additions: dict[str, str] = {}
```

Add:

```python
    def _config(self) -> GatewayConfig:
        if self._config_obj is None:
            self._config_obj = load_config(self.config_path)
        return self._config_obj

    def _migrate_config_and_env(self, selected: set[str]) -> None:
        raw_config = _load_yaml(self.source / "config.yaml")
        env_values = _load_env_file(self.source / ".env")
        if "model-config" in selected:
            self._migrate_model_config(raw_config)
        if "provider-keys" in selected or "search-config" in selected:
            self._migrate_env_values(env_values)
        if "mcp-servers" in selected:
            self._migrate_mcp_servers(raw_config)
        self._migrate_channels(raw_config, env_values, selected)

    def _migrate_model_config(self, raw_config: dict[str, Any]) -> None:
        model_cfg = raw_config.get("model") if isinstance(raw_config.get("model"), dict) else {}
        provider = str(model_cfg.get("provider") or "").strip()
        model = str(model_cfg.get("model") or model_cfg.get("default") or "").strip()
        if not provider and not model:
            self._record("model-config", self.source / "config.yaml", self.config_path, "skipped")
            return
        cfg = self._config()
        if provider:
            cfg.llm.provider = provider
            cfg.llm.api_key_env = PROVIDER_ENV_KEYS.get(provider, cfg.llm.api_key_env)
        if model:
            cfg.llm.model = model
        base_url = model_cfg.get("base_url") or model_cfg.get("baseUrl")
        if base_url:
            cfg.llm.base_url = str(base_url)
        self._config_changed = True
        self._record("model-config", self.source / "config.yaml", self.config_path, "migrated" if self.options.apply else "planned")

    def _migrate_env_values(self, env_values: dict[str, str]) -> None:
        migrated = 0
        for key, value in env_values.items():
            target_key = "BRAVE_SEARCH_API_KEY" if key == "BRAVE_API_KEY" else key
            if target_key not in SECRET_ENV_KEYS or not value:
                continue
            if not self.options.migrate_secrets:
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
            "pass --migrate-secrets to migrate recognized secrets" if env_values and not migrated else "",
            {"migrated_keys": [SECRET_REDACTION] * migrated},
        )

    def _migrate_mcp_servers(self, raw_config: dict[str, Any]) -> None:
        servers = raw_config.get("mcp", {}).get("servers", {}) if isinstance(raw_config.get("mcp"), dict) else {}
        if not isinstance(servers, dict) or not servers:
            self._record("mcp-servers", self.source / "config.yaml", self.config_path, "skipped")
            return
        entries = []
        for name, raw in servers.items():
            if not isinstance(raw, dict):
                continue
            entry = {"name": name}
            for key in ("command", "args", "env", "url"):
                if key in raw:
                    entry[key] = raw[key]
            entries.append(MCPServerEntry.model_validate(entry))
        cfg = self._config()
        cfg.mcp.enabled = True
        cfg.mcp.servers = entries
        self._config_changed = True
        self._record("mcp-servers", self.source / "config.yaml", self.config_path, "migrated" if self.options.apply else "planned")

    def _migrate_channels(self, raw_config: dict[str, Any], env_values: dict[str, str], selected: set[str]) -> None:
        raw_entries = [entry.model_dump(mode="python") for entry in self._config().channels.channels]
        def upsert(entry: dict[str, Any]) -> None:
            for idx, existing in enumerate(raw_entries):
                if existing.get("name") == entry["name"]:
                    raw_entries[idx] = entry
                    return
            raw_entries.append(entry)
        if "telegram-settings" in selected and self.options.migrate_secrets and env_values.get("TELEGRAM_BOT_TOKEN"):
            telegram = raw_config.get("telegram", {}) if isinstance(raw_config.get("telegram"), dict) else {}
            upsert({"name": "hermes-telegram", "type": "telegram", "token": env_values["TELEGRAM_BOT_TOKEN"], "default_chat_id": str(telegram.get("default_chat_id", ""))})
        if "discord-settings" in selected and self.options.migrate_secrets and env_values.get("DISCORD_BOT_TOKEN"):
            discord = raw_config.get("discord", {}) if isinstance(raw_config.get("discord"), dict) else {}
            upsert({"name": "hermes-discord", "type": "discord", "token": env_values["DISCORD_BOT_TOKEN"], "default_channel_id": str(discord.get("default_channel_id", ""))})
        if "slack-settings" in selected and self.options.migrate_secrets and env_values.get("SLACK_BOT_TOKEN"):
            slack = raw_config.get("slack", {}) if isinstance(raw_config.get("slack"), dict) else {}
            upsert({"name": "hermes-slack", "type": "slack", "token": env_values["SLACK_BOT_TOKEN"], "slack_channel_id": str(slack.get("channel_id", ""))})
        cfg = self._config()
        cfg.channels = ChannelsConfig.model_validate({"channels": raw_entries})
        self._config_changed = True
```

Add write helpers:

```python
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
```

Call `_migrate_config_and_env(selected)` after `_plan_user_data(selected)`, then `_write_config()` and `_write_env()` before `_write_reports()`.

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_migration/test_hermes_migration.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/opensquilla/migration/hermes.py tests/test_migration/test_hermes_migration.py
git commit -m "Map Hermes config and secrets"
```

## Task 5: Archive Unsupported Hermes Runtime and Config Artifacts

**Files:**
- Modify: `src/opensquilla/migration/hermes.py`
- Modify: `tests/test_migration/test_hermes_migration.py`

- [ ] **Step 1: Add archive test**

Append:

```python
def test_archive_unsupported_runtime_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
```

- [ ] **Step 2: Run test and verify failure**

```bash
uv run pytest tests/test_migration/test_hermes_migration.py::test_archive_unsupported_runtime_artifacts -q
```

Expected: fail because archive handling is missing.

- [ ] **Step 3: Implement archive/skip policy**

Add constants:

```python
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
```

Add methods:

```python
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
            self._record(kind, source, destination, "archived" if self.options.apply else "planned")
        for name in sorted(SKIP_SOURCE_ARTIFACTS):
            source = self.source / name
            if source.exists():
                self._record(name, source, None, "skipped", "runtime or credential artifact is not imported")
```

Call `_archive_unsupported(selected)` before reports.

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_migration/test_hermes_migration.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/opensquilla/migration/hermes.py tests/test_migration/test_hermes_migration.py
git commit -m "Archive unsupported Hermes artifacts"
```

## Task 6: Add CLI Command

**Files:**
- Modify: `src/opensquilla/cli/migrate_cmd.py`
- Modify: `tests/test_migration/test_hermes_e2e.py`

- [ ] **Step 1: Add CLI dry-run test**

Create `tests/test_migration/test_hermes_e2e.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from opensquilla.cli.main import app

runner = CliRunner()


def _write_hermes_home(root: Path) -> Path:
    source = root / ".hermes"
    source.mkdir()
    (source / "config.yaml").write_text("model:\n  provider: openrouter\n  model: openai/gpt-4o-mini\n", encoding="utf-8")
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
```

- [ ] **Step 2: Run test and verify failure**

```bash
uv run pytest tests/test_migration/test_hermes_e2e.py -q
```

Expected: fail because CLI command does not exist.

- [ ] **Step 3: Wire CLI command**

Modify imports in `src/opensquilla/cli/migrate_cmd.py`:

```python
from opensquilla.migration.hermes import (
    MIGRATION_OPTIONS as HERMES_MIGRATION_OPTIONS,
    MIGRATION_PRESETS as HERMES_MIGRATION_PRESETS,
    SKILL_CONFLICT_MODES as HERMES_SKILL_CONFLICT_MODES,
    HermesMigrationOptions,
    HermesMigrator,
)
```

Add helper:

```python
def _reject_invalid_hermes_options(
    *,
    preset: str,
    include: tuple[str, ...],
    exclude: tuple[str, ...],
    skill_conflict: str,
) -> None:
    if preset not in HERMES_MIGRATION_PRESETS:
        typer.echo(f"Unknown Hermes migration preset: {preset}")
        raise typer.Exit(2)
    unknown_include = sorted(set(include) - HERMES_MIGRATION_OPTIONS)
    if unknown_include:
        typer.echo(f"Unknown Hermes migration option in include: {', '.join(unknown_include)}")
        raise typer.Exit(2)
    unknown_exclude = sorted(set(exclude) - HERMES_MIGRATION_OPTIONS)
    if unknown_exclude:
        typer.echo(f"Unknown Hermes migration option in exclude: {', '.join(unknown_exclude)}")
        raise typer.Exit(2)
    if skill_conflict not in HERMES_SKILL_CONFLICT_MODES:
        typer.echo(f"Unknown Hermes skill conflict behavior: {skill_conflict}")
        raise typer.Exit(2)
```

Add command:

```python
@migrate_app.command("hermes")
def migrate_hermes(
    source: Path | None = typer.Option(None, "--source", help="Hermes home directory."),
    profile: str | None = typer.Option(None, "--profile", help="Hermes profile name under ~/.hermes/profiles."),
    config: Path | None = typer.Option(None, "--config", help="OpenSquilla config path to write or preview."),
    apply: bool = typer.Option(False, "--apply", help="Apply the migration. Without this flag, only a dry-run report is produced."),
    migrate_secrets: bool = typer.Option(False, "--migrate-secrets", help="Copy recognized secrets. Defaults to false."),
    overwrite: bool = typer.Option(False, "--overwrite", help="Overwrite target workspace files after making item-level backups."),
    preset: str = typer.Option("full", "--preset", help="Migration preset: user-data or full."),
    include: list[str] | None = typer.Option(None, "--include", help="Comma-separated migration option ids to include."),
    exclude: list[str] | None = typer.Option(None, "--exclude", help="Comma-separated migration option ids to exclude."),
    skill_conflict: str = typer.Option("skip", "--skill-conflict", help="Skill conflict behavior: skip, overwrite, or rename."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Migrate Hermes Agent state into OpenSquilla-native files."""

    include_options = _split_csv(include)
    exclude_options = _split_csv(exclude)
    _reject_invalid_hermes_options(
        preset=preset,
        include=include_options,
        exclude=exclude_options,
        skill_conflict=skill_conflict,
    )
    options = HermesMigrationOptions(
        source=source,
        profile=profile,
        config_path=config,
        apply=apply,
        migrate_secrets=migrate_secrets,
        overwrite=overwrite,
        preset=preset,
        include=include_options,
        exclude=exclude_options,
        skill_conflict=skill_conflict,  # type: ignore[arg-type]
    )
    if json_output:
        with contextlib.redirect_stdout(io.StringIO()):
            report = HermesMigrator(options).migrate()
    else:
        report = HermesMigrator(options).migrate()
    has_error = any(item.get("status") == "error" for item in report.get("items", []))
    if json_output:
        typer.echo(json.dumps(report, ensure_ascii=False))
    else:
        mode = "applied" if apply else "dry-run"
        console.print(f"[green]Hermes migration complete[/green] ({mode})")
        console.print(f"[dim]Report:[/dim] {report['output_dir']}")
    if has_error:
        raise typer.Exit(1)
```

- [ ] **Step 4: Run CLI test**

```bash
uv run pytest tests/test_migration/test_hermes_e2e.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/opensquilla/cli/migrate_cmd.py tests/test_migration/test_hermes_e2e.py
git commit -m "Add Hermes migration CLI"
```

## Task 7: Realistic E2E and Regression Suite

**Files:**
- Modify: `tests/test_migration/test_hermes_e2e.py`

- [ ] **Step 1: Add realistic apply test**

Append a second test to `tests/test_migration/test_hermes_e2e.py`:

```python
import tomllib


def test_cli_hermes_apply_preserves_existing_config_and_redacts_report(tmp_path: Path, monkeypatch) -> None:
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
    assert config["llm"]["provider"] == "openrouter"
    assert config["llm"]["model"] == "anthropic/claude-3.5-sonnet"
    assert config["channels"]["channels"][0]["type"] == "telegram"
    assert (Path(report["output_dir"]) / "report.json").is_file()
```

- [ ] **Step 2: Run focused migration tests**

```bash
uv run pytest tests/test_migration/test_hermes_migration.py tests/test_migration/test_hermes_e2e.py -q
```

Expected: pass.

- [ ] **Step 3: Run OpenClaw regression tests**

```bash
uv run pytest tests/test_migration/test_openclaw_migration.py tests/test_migration/test_openclaw_e2e.py -q
```

Expected: pass unchanged.

- [ ] **Step 4: Run lint on touched files**

```bash
uv run ruff check src/opensquilla/migration/hermes.py src/opensquilla/cli/migrate_cmd.py tests/test_migration/test_hermes_migration.py tests/test_migration/test_hermes_e2e.py
```

Expected: no violations.

- [ ] **Step 5: Commit**

```bash
git add tests/test_migration/test_hermes_e2e.py
git commit -m "Cover Hermes migration end to end"
```

## Final Verification

- [ ] Run focused Hermes suite:

```bash
uv run pytest tests/test_migration/test_hermes_migration.py tests/test_migration/test_hermes_e2e.py -q
```

- [ ] Run migration regression suite:

```bash
uv run pytest tests/test_migration/test_openclaw_migration.py tests/test_migration/test_openclaw_e2e.py tests/test_migration/test_hermes_migration.py tests/test_migration/test_hermes_e2e.py -q
```

- [ ] Run lint:

```bash
uv run ruff check src/opensquilla/migration/hermes.py src/opensquilla/cli/migrate_cmd.py tests/test_migration/test_hermes_migration.py tests/test_migration/test_hermes_e2e.py
```

- [ ] Manual CLI smoke:

```bash
uv run opensquilla migrate hermes --source path/to/synthetic/.hermes --json
```

Expected: JSON report with `"apply": false`, no target writes, and no secret values.

## Self-Review Notes

- Spec coverage: plan covers CLI, source detection, dry-run, apply, secrets opt-in, redaction, persona/memory/user profile, skills, model/provider/search, Telegram/Discord/Slack, MCP, unsupported runtime archival, reports, and regression tests.
- Intentional first-version exclusions: live session import, `state.db`, `auth.json`, logs, caches, checkpoints, browser profile state, and unsupported channels are skipped or archived.
- Risk to watch during implementation: exact Hermes `config.yaml` field names may differ across Hermes versions. Tests should use fields confirmed from the local Hermes code before finalizing mapping aliases.
