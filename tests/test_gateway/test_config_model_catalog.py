"""Schema tests for the ``[model_catalog]`` and ``[models]`` config sections.

Both sections land schema-first: defaults reproduce current behavior (no
catalog refresh, no per-model overrides) and nothing consumes them in the
provider layer yet. Covered here:

* validation — refresh literal, ge bounds, extra-forbid override entries,
  and the conservative reasoning_format dialect set;
* TOML quoted-key parsing for model ids containing dots and slashes;
* to_toml_dict / persist round-trips (``exclude_defaults=False`` means both
  sections always materialize on a full-tree persist);
* migration-framework compatibility — an existing payload without the
  sections loads with ``changed`` False and picks up pure defaults.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import tomli_w
from pydantic import ValidationError

from opensquilla.gateway.config import (
    KNOWN_REASONING_FORMATS,
    GatewayConfig,
    ModelCatalogConfig,
    ModelOverrideConfig,
)
from opensquilla.gateway.config_migration import (
    LATEST_CONFIG_VERSION,
    migrate_config_payload,
)
from opensquilla.onboarding import config_store

# ---------------------------------------------------------------------------
# [model_catalog] schema
# ---------------------------------------------------------------------------


def test_model_catalog_defaults_are_offline_first() -> None:
    cfg = GatewayConfig()

    assert cfg.model_catalog.refresh == "off"
    assert cfg.model_catalog.pin_path == ""
    assert cfg.model_catalog.stale_after_days == 45


def test_model_catalog_accepts_startup_refresh_and_pin_path() -> None:
    cfg = GatewayConfig.model_validate(
        {
            "model_catalog": {
                "refresh": "startup",
                "pin_path": "/srv/airgap/model-catalog.json",
                "stale_after_days": 7,
            }
        }
    )

    assert cfg.model_catalog.refresh == "startup"
    assert cfg.model_catalog.pin_path == "/srv/airgap/model-catalog.json"
    assert cfg.model_catalog.stale_after_days == 7


@pytest.mark.parametrize("bad_refresh", ["daily", "on", "always", ""])
def test_model_catalog_rejects_unknown_refresh_values(bad_refresh: str) -> None:
    with pytest.raises(ValidationError):
        GatewayConfig.model_validate({"model_catalog": {"refresh": bad_refresh}})


@pytest.mark.parametrize("bad_days", [0, -1])
def test_model_catalog_stale_after_days_must_be_at_least_one(bad_days: int) -> None:
    with pytest.raises(ValidationError):
        GatewayConfig.model_validate({"model_catalog": {"stale_after_days": bad_days}})


def test_model_catalog_env_prefix_binds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENSQUILLA_MODEL_CATALOG_REFRESH", "startup")
    monkeypatch.setenv("OPENSQUILLA_MODEL_CATALOG_STALE_AFTER_DAYS", "10")

    catalog = ModelCatalogConfig()

    assert catalog.refresh == "startup"
    assert catalog.stale_after_days == 10


# ---------------------------------------------------------------------------
# [models] override schema
# ---------------------------------------------------------------------------


def test_models_defaults_to_empty_mapping() -> None:
    assert GatewayConfig().models == {}


def test_models_toml_quoted_keys_parse(tmp_path: Path) -> None:
    """Model ids carrying dots/slashes must survive as TOML quoted keys."""
    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        "\n".join(
            [
                '[models.custom."qwen3-32b-awq"]',
                "context_window = 131072",
                "max_output_tokens = 8192",
                "supports_tools = true",
                "",
                '[models.openrouter."z-ai/glm-5.2"]',
                'reasoning_format = "openrouter"',
                "supports_reasoning = true",
                "input_cost_per_mtok = 0.5",
                "output_cost_per_mtok = 2.0",
                "cache_read_cost_per_mtok = 0.05",
                "cache_write_cost_per_mtok = 0.6",
                'thinking_level_map = { high = "high", medium = "medium" }',
                "",
            ]
        ),
        encoding="utf-8",
    )

    cfg = GatewayConfig.load(toml_path)

    custom = cfg.models["custom"]["qwen3-32b-awq"]
    assert custom.context_window == 131072
    assert custom.max_output_tokens == 8192
    assert custom.supports_tools is True
    assert custom.reasoning_format is None  # unset fields stay "no override"

    glm = cfg.models["openrouter"]["z-ai/glm-5.2"]
    assert glm.reasoning_format == "openrouter"
    assert glm.supports_reasoning is True
    assert glm.input_cost_per_mtok == 0.5
    assert glm.output_cost_per_mtok == 2.0
    assert glm.cache_read_cost_per_mtok == 0.05
    assert glm.cache_write_cost_per_mtok == 0.6
    assert glm.thinking_level_map == {"high": "high", "medium": "medium"}


def test_model_override_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        GatewayConfig.model_validate(
            {"models": {"custom": {"qwen3-32b-awq": {"context_windw": 131072}}}}
        )


@pytest.mark.parametrize(
    "override",
    [
        {"context_window": 0},
        {"max_output_tokens": 0},
        {"input_cost_per_mtok": -0.1},
        {"output_cost_per_mtok": -1},
        {"cache_read_cost_per_mtok": -0.01},
        {"cache_write_cost_per_mtok": -1},
    ],
    ids=[
        "context-window",
        "max-output",
        "input-cost",
        "output-cost",
        "cache-read-cost",
        "cache-write-cost",
    ],
)
def test_model_override_rejects_out_of_range_values(override: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        GatewayConfig.model_validate({"models": {"custom": {"m": override}}})


def test_model_override_accepts_cache_cost_fields() -> None:
    override = ModelOverrideConfig(
        input_cost_per_mtok=0.2, cache_read_cost_per_mtok=0.05, cache_write_cost_per_mtok=0.6
    )
    assert override.cache_read_cost_per_mtok == 0.05
    assert override.cache_write_cost_per_mtok == 0.6


@pytest.mark.parametrize("dialect", sorted(KNOWN_REASONING_FORMATS))
def test_reasoning_format_accepts_every_known_dialect(dialect: str) -> None:
    override = ModelOverrideConfig(reasoning_format=dialect)
    assert override.reasoning_format == dialect


def test_reasoning_format_normalizes_case_and_whitespace() -> None:
    assert ModelOverrideConfig(reasoning_format=" OpenAI ").reasoning_format == "openai"


def test_reasoning_format_rejects_unknown_dialect() -> None:
    with pytest.raises(ValidationError, match="not a known dialect"):
        ModelOverrideConfig(reasoning_format="mystery-dialect")


def test_glob_looking_keys_are_allowed_but_inert() -> None:
    """Globs are not supported: keys are exact-match only, but glob-looking
    strings are still accepted (a never-matching key is harmless, and key
    screening could reject unusual legitimate model ids)."""
    cfg = GatewayConfig.model_validate(
        {"models": {"openrouter": {"z-ai/*": {"supports_vision": False}}}}
    )
    assert cfg.models["openrouter"]["z-ai/*"].supports_vision is False


# ---------------------------------------------------------------------------
# to_toml_dict / persist round-trips
# ---------------------------------------------------------------------------


def test_to_toml_dict_always_materializes_both_sections() -> None:
    """to_toml_dict dumps with exclude_defaults=False, so a full-tree persist
    always writes the sections — the documented downgrade caveat."""
    data = GatewayConfig().to_toml_dict()

    assert data["model_catalog"] == {
        "refresh": "off",
        "pin_path": "",
        "stale_after_days": 45,
    }
    assert data["models"] == {}


def test_to_toml_dict_drops_unset_override_fields() -> None:
    cfg = GatewayConfig.model_validate(
        {"models": {"custom": {"qwen3-32b-awq": {"context_window": 131072}}}}
    )

    data = cfg.to_toml_dict()

    # exclude_none=True keeps the entry TOML-serializable: only set fields.
    assert data["models"] == {"custom": {"qwen3-32b-awq": {"context_window": 131072}}}


def test_persist_round_trip_preserves_catalog_and_overrides(tmp_path: Path) -> None:
    payload = {
        "model_catalog": {"refresh": "startup", "pin_path": "/srv/catalog.toml"},
        "models": {
            "custom": {"qwen3-32b-awq": {"context_window": 131072}},
            "openrouter": {
                "z-ai/glm-5.2": {
                    "reasoning_format": "openrouter",
                    "input_cost_per_mtok": 0.5,
                }
            },
        },
    }
    source = tmp_path / "config.toml"
    with source.open("wb") as fh:
        tomli_w.dump(payload, fh)

    cfg = config_store.load_config(source)
    target = tmp_path / "persisted.toml"
    config_store.persist_config(cfg, path=target, backup=False)
    reloaded = config_store.load_config(target)

    assert reloaded.model_catalog.refresh == "startup"
    assert reloaded.model_catalog.pin_path == "/srv/catalog.toml"
    assert reloaded.model_catalog.stale_after_days == 45
    assert reloaded.models == cfg.models
    assert reloaded.models["custom"]["qwen3-32b-awq"].context_window == 131072
    glm = reloaded.models["openrouter"]["z-ai/glm-5.2"]
    assert glm.reasoning_format == "openrouter"
    assert glm.input_cost_per_mtok == 0.5


# ---------------------------------------------------------------------------
# Migration framework: purely additive, no migration fires
# ---------------------------------------------------------------------------


def test_existing_payload_without_sections_loads_unchanged() -> None:
    """A pre-0.5.x-shaped payload (no model_catalog/models keys) must load
    without triggering a migration rewrite and pick up pure defaults."""
    payload = {
        "config_version": LATEST_CONFIG_VERSION,
        "host": "127.0.0.1",
        "port": 18791,
        "llm": {"provider": "openrouter", "model": "deepseek/deepseek-v4-pro"},
    }

    result = migrate_config_payload(payload)

    assert result.changed is False
    assert "model_catalog" not in result.payload
    assert "models" not in result.payload
    cfg = GatewayConfig.model_validate(result.payload)
    assert cfg.model_catalog.refresh == "off"
    assert cfg.models == {}


def test_file_without_sections_is_not_rewritten_on_load(tmp_path: Path) -> None:
    toml_path = tmp_path / "config.toml"
    with toml_path.open("wb") as fh:
        tomli_w.dump({"port": 18791}, fh)
    original_bytes = toml_path.read_bytes()

    cfg = GatewayConfig.load(toml_path)

    assert cfg.model_catalog.refresh == "off"
    assert cfg.models == {}
    assert toml_path.read_bytes() == original_bytes
    assert not list(tmp_path.glob("config.toml.backup.*"))
