"""Tests for legacy memory field fallback in GatewayConfig.

Verifies that deprecated memory.* fields in old config files are silently
dropped rather than causing ValidationError, and that a single aggregated
DeprecationWarning is emitted per process.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

import opensquilla.gateway.config as config_module
import opensquilla.gateway.config_migration as migration_module
from opensquilla.gateway.config import GatewayConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ALL_DEPRECATED_MEMORY_FIELDS = {
    "memory.profile": "legacy_profile_value",
    "memory.cost.embedding_cache": "true",
    "memory.cost.rerank_cache": "false",
    "memory.cost.llm_judge_cache": "true",
    "memory.facts_enabled": "true",
    "memory.facts_top_k": "5",
    "memory.facts_max_chars": "2000",
    "memory.multi_hop_enabled": "false",
    "memory.multi_hop_max_depth": "3",
    "memory.multi_hop_score_threshold": "0.7",
    "memory.recall_frequency": "always",
    "memory.recall_top_k_default": "10",
    "memory.auto_recall_enabled": "true",
    "memory.prefetch_enabled": "true",
    "memory.prefetch_max_results": "3",
    "memory.prefetch_min_score": "0.3",
    "memory.prefetch_total_max_chars": "1500",
    "memory.semantic_chunking_enabled": "true",
    "memory.eviction_policy": "lru",
    "memory.summary_model": "gpt-4o-mini",
    "memory.summary_max_tokens": "256",
}


def test_explicit_missing_config_path_stays_attached_to_defaults(tmp_path: Path) -> None:
    target = tmp_path / "new-user-config.toml"

    cfg = GatewayConfig.load(target)

    assert cfg.config_path == str(target)
    assert not target.exists()


def _build_toml_with_deprecated(tmp_path: Path) -> Path:
    """Write a minimal config.toml that contains all deprecated fields."""
    lines = ["[memory]\n"]
    cost_lines = ["[memory.cost]\n"]

    for dotted, val in _ALL_DEPRECATED_MEMORY_FIELDS.items():
        parts = dotted.split(".")
        if parts[1] == "cost":
            leaf = parts[2]
            cost_lines.append(f'{leaf} = "{val}"\n')
        else:
            leaf = parts[1]
            lines.append(f'{leaf} = "{val}"\n')

    toml_path = tmp_path / "config.toml"
    toml_path.write_text("".join(lines) + "\n" + "".join(cost_lines))
    return toml_path


# ---------------------------------------------------------------------------
# AC#1 / AC#4: loading does not raise
# ---------------------------------------------------------------------------


def test_load_with_all_deprecated_fields_does_not_raise(tmp_path: Path) -> None:
    """GatewayConfig.load() must succeed even when deprecated memory
    fields are present in the config file."""
    toml_path = _build_toml_with_deprecated(tmp_path)
    cfg = GatewayConfig.load(toml_path)
    assert isinstance(cfg, GatewayConfig)
    backups = sorted(tmp_path.glob("config.toml.backup.*"))
    assert backups
    backup_text = backups[-1].read_text(encoding="utf-8")
    assert "prefetch_enabled" in backup_text
    assert "embedding_cache" in backup_text
    text = toml_path.read_text(encoding="utf-8")
    assert "prefetch_enabled" not in text
    assert "embedding_cache" not in text


def test_load_migrates_010_turn_capture_fields(tmp_path: Path) -> None:
    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        "\n".join(
            [
                "[memory]",
                'capture_mode = "archive_turn_pair"',
                "index_captured_turns = true",
                "prefetch_enabled = true",
                "prefetch_max_results = 3",
                "prefetch_min_score = 0.3",
                "",
            ]
        ),
        encoding="utf-8",
    )

    cfg = GatewayConfig.load(toml_path)

    assert cfg.memory.capture_mode == "turn_pair"
    backups = sorted(tmp_path.glob("config.toml.backup.*"))
    assert backups
    backup_text = backups[-1].read_text(encoding="utf-8")
    assert 'capture_mode = "archive_turn_pair"' in backup_text
    assert "index_captured_turns = true" in backup_text
    data = toml_path.read_text(encoding="utf-8")
    assert 'capture_mode = "turn_pair"' in data
    assert "archive_turn_pair" not in data
    assert "index_captured_turns" not in data
    assert "prefetch_enabled" not in data
    assert "prefetch_max_results" not in data
    assert "prefetch_min_score" not in data


def test_load_from_toml_migrates_010_turn_capture_fields(tmp_path: Path) -> None:
    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        "\n".join(
            [
                "[memory]",
                'capture_mode = "archive_turn_pair"',
                "index_captured_turns = false",
                "",
            ]
        ),
        encoding="utf-8",
    )

    cfg = GatewayConfig.load_from_toml(toml_path)

    assert cfg.memory.capture_mode == "turn_pair"
    backups = sorted(tmp_path.glob("config.toml.backup.*"))
    assert backups
    backup_text = backups[-1].read_text(encoding="utf-8")
    assert 'capture_mode = "archive_turn_pair"' in backup_text
    data = toml_path.read_text(encoding="utf-8")
    assert 'capture_mode = "turn_pair"' in data
    assert "index_captured_turns" not in data


def test_load_migrates_legacy_agent_token_saving_fields(tmp_path: Path) -> None:
    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        "\n".join(
            [
                "[agent_token_saving]",
                "tool_result_compression_enabled = false",
                'tool_result_compression_mode = "off"',
                "tool_result_compression_max_share = 0.25",
                'tool_result_compression_summary_model = "z-ai/glm-4.5-air"',
                "tool_result_compression_summary_max_tokens = 512",
                "tool_result_compression_summary_timeout_seconds = 12.5",
                "tool_result_compression_summary_input_max_chars = 43210",
                "tool_result_store_max_bytes = 1234",
                "tool_result_store_disk_budget_bytes = 5678",
                "tool_result_store_retention_seconds = 90",
                "",
            ]
        ),
        encoding="utf-8",
    )

    cfg = GatewayConfig.load(toml_path)

    assert cfg.agent_token_saving.tool_result_projection_max_inline_chars == 43210
    backups = sorted(tmp_path.glob("config.toml.backup.*"))
    assert backups
    backup_text = backups[-1].read_text(encoding="utf-8")
    assert "tool_result_compression_enabled = false" in backup_text
    migrated = toml_path.read_text(encoding="utf-8")
    assert "tool_result_compression_" not in migrated
    assert "tool_result_projection_max_inline_chars = 43210" in migrated
    assert "tool_result_store_" not in migrated


def test_legacy_agent_token_saving_migration_preserves_new_projection_setting(
    tmp_path: Path,
) -> None:
    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        "\n".join(
            [
                "[agent_token_saving]",
                "tool_result_projection_max_inline_chars = 22222",
                "tool_result_compression_summary_input_max_chars = 60000",
                "tool_result_compression_enabled = true",
                "",
            ]
        ),
        encoding="utf-8",
    )

    cfg = GatewayConfig.load_from_toml(toml_path)

    assert cfg.agent_token_saving.tool_result_projection_max_inline_chars == 22222
    migrated = toml_path.read_text(encoding="utf-8")
    assert "tool_result_projection_max_inline_chars = 22222" in migrated
    assert "tool_result_compression_" not in migrated


def test_legacy_agent_token_saving_migration_keeps_runtime_schema_strict(
    tmp_path: Path,
) -> None:
    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        "\n".join(
            [
                "[agent_token_saving]",
                "tool_result_compression_enabled = true",
                "tool_result_compression_summary_input_max_chars = 60000",
                "typo_field = true",
                "",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError) as exc_info:
        GatewayConfig.load(toml_path)

    assert "agent_token_saving.typo_field" in str(exc_info.value)


# ---------------------------------------------------------------------------
# AC#5: aggregate DeprecationWarning emitted once per process
# ---------------------------------------------------------------------------


def test_aggregate_deprecation_warning_emitted_once_per_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A single DeprecationWarning is emitted the first time deprecated memory
    fields are encountered; subsequent loads with the same fields are silent."""
    # Reset the process-level sentinels so this test is not affected by order.
    monkeypatch.setattr(migration_module, "_LEGACY_MEMORY_FIELDS_WARNED", False)
    monkeypatch.setattr(migration_module, "_LEGACY_MEMORY_FIELDS_SEEN", set())

    toml_path = _build_toml_with_deprecated(tmp_path)

    with pytest.warns(DeprecationWarning) as record:
        GatewayConfig.load(toml_path)
        # Second load — sentinel is now True, should not add another warning.
        GatewayConfig.load(toml_path)

    deprecation_warnings = [
        w for w in record.list if issubclass(w.category, DeprecationWarning)
    ]
    assert len(deprecation_warnings) == 1, (
        f"Expected exactly 1 DeprecationWarning, got {len(deprecation_warnings)}: "
        f"{[str(w.message) for w in deprecation_warnings]}"
    )
    msg = str(deprecation_warnings[0].message)
    assert "memory" in msg.lower()
    assert f"{len(_ALL_DEPRECATED_MEMORY_FIELDS)} legacy memory.* config field(s) ignored" in msg
    assert "0.2.0" in msg


# ---------------------------------------------------------------------------
# AC#6: log file written with per-field detail
# ---------------------------------------------------------------------------


def test_log_file_written_with_per_field_detail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """After loading a config with deprecated fields, a .log file must exist
    under ~/.opensquilla/logs/ containing one JSON line per deprecated field."""
    monkeypatch.setattr(migration_module, "_LEGACY_MEMORY_FIELDS_WARNED", False)
    monkeypatch.setattr(migration_module, "_LEGACY_MEMORY_FIELDS_SEEN", set())

    # Redirect opensquilla home to tmp_path so the log lands there.
    monkeypatch.setattr(migration_module, "default_opensquilla_home", lambda: tmp_path)

    toml_path = _build_toml_with_deprecated(tmp_path)

    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("always")
        GatewayConfig.load(toml_path)

    logs_dir = tmp_path / "logs"
    assert logs_dir.exists(), "logs/ directory was not created"

    log_files = sorted(logs_dir.glob("legacy_config_*.log"))
    assert len(log_files) >= 1, f"No legacy_config_*.log found in {logs_dir}"

    log_file = log_files[-1]
    lines = [ln for ln in log_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
    expected_count = len(_ALL_DEPRECATED_MEMORY_FIELDS)
    assert len(lines) == expected_count, f"Expected {expected_count} log lines, got {len(lines)}"

    for line in lines:
        entry = json.loads(line)
        assert "field" in entry
        assert "timestamp" in entry
        assert "source" in entry


# ---------------------------------------------------------------------------
# AC#8 guard: no OPENSQUILLA_LEGACY_FALLBACK env switch
# ---------------------------------------------------------------------------


def test_no_legacy_fallback_env_var() -> None:
    """The source must not contain an OPENSQUILLA_LEGACY_FALLBACK env switch
    (ADR-3 prohibits runtime opt-out of the fallback)."""
    import inspect
    source = inspect.getsource(config_module)
    assert "OPENSQUILLA_LEGACY_FALLBACK" not in source


class TestMetaSkillConfig:
    """C4: GatewayConfig must accept [meta_skill.persistence] section."""

    def test_default_meta_skill_config(self) -> None:
        from opensquilla.gateway.config import GatewayConfig

        cfg = GatewayConfig()
        assert cfg.meta_skill.persistence.enabled is True
        assert cfg.meta_skill.persistence.orphan_cleanup_age_seconds == 3600

    def test_meta_skill_persistence_disabled(self) -> None:
        from opensquilla.gateway.config import GatewayConfig

        cfg = GatewayConfig(
            meta_skill={"persistence": {"enabled": False}},
        )
        assert cfg.meta_skill.persistence.enabled is False

    def test_meta_skill_env_override(self, monkeypatch) -> None:
        from opensquilla.gateway.config import MetaSkillPersistenceConfig

        monkeypatch.setenv("OPENSQUILLA_META_SKILL_PERSISTENCE_ENABLED", "false")
        cfg = MetaSkillPersistenceConfig()
        assert cfg.enabled is False

    def test_example_toml_parses_clean(self) -> None:
        """Copying opensquilla.toml.example to ~/.opensquilla/config.toml must work."""
        import tomllib
        from pathlib import Path

        from opensquilla.gateway.config import GatewayConfig

        example_path = Path(__file__).resolve().parents[1] / "opensquilla.toml.example"
        with example_path.open("rb") as f:
            data = tomllib.load(f)

        # No exceptions during validation
        GatewayConfig(**data)
