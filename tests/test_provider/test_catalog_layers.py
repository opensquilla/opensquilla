"""Layered model-catalog resolution (ModelCatalog.resolve_entry).

Covers per-field authority merging (user > live > corrections > snapshot >
synthesized), glob corrections matching, per-1k → per-Mtok cost adaptation,
cold-instance resolution, override validation — plus a parity net asserting
the legacy resolve paths still return today's exact values.
"""

from __future__ import annotations

import tomllib
from importlib import resources

import pytest

from opensquilla.provider import model_catalog as model_catalog_module
from opensquilla.provider.model_catalog import ModelCatalog


def _install_corrections(monkeypatch: pytest.MonkeyPatch, toml_text: str) -> None:
    """Route the corrections layer at parsed TOML text (packaged file is empty)."""
    tables = model_catalog_module._normalize_corrections(tomllib.loads(toml_text))
    monkeypatch.setattr(model_catalog_module, "_corrections_tables", lambda: tables)


# ---------------------------------------------------------------------------
# Cold instance — a bare ModelCatalog() with no network warmup must resolve
# through corrections + snapshot + synthesized (ensemble.py builds bare
# instances per member).
# ---------------------------------------------------------------------------


def test_cold_instance_resolves_snapshot_known_model() -> None:
    entry = ModelCatalog().resolve_entry("gpt-5.5", provider="openai")

    assert entry.source == "snapshot"
    assert entry.provider_id == "openai"
    assert entry.model_id == "gpt-5.5"
    assert entry.context_window == 1_050_000
    assert entry.max_output_tokens == 128_000
    assert entry.supports_reasoning is True
    assert entry.supports_tools is True
    assert entry.supports_vision is True
    # The snapshot never knows the streaming dialect.
    assert entry.reasoning_format == "none"
    assert entry.input_cost_per_mtok is None


def test_cold_instance_synthesizes_unknown_model() -> None:
    entry = ModelCatalog().resolve_entry("model-that-does-not-exist-anywhere")

    assert entry.source == "synthesized"
    assert entry.context_window == 32_768
    assert entry.max_output_tokens == 8_192
    assert entry.supports_tools is True
    assert entry.supports_reasoning is False
    assert entry.supports_vision is False
    assert entry.input_cost_per_mtok is None
    assert entry.output_cost_per_mtok is None
    assert entry.quality_prior is None


# ---------------------------------------------------------------------------
# Per-field authority merging
# ---------------------------------------------------------------------------


def _populated_catalog() -> ModelCatalog:
    catalog = ModelCatalog()
    catalog._populate_from_data(
        [
            {
                "id": "vendor/model-x",
                "name": "Vendor Model X",
                "context_length": 200_000,
                "top_provider": {"max_completion_tokens": 30_000},
                "supported_parameters": ["tools", "reasoning"],
                "architecture": {"input_modalities": ["text", "image"]},
                "pricing": {"prompt": "0.0000025", "completion": "0.00001"},
            }
        ]
    )
    return catalog


def test_user_overrides_beat_live_per_field() -> None:
    catalog = _populated_catalog()
    catalog.set_user_overrides(
        {"openrouter/vendor/model-x": {"context_window": 111, "quality_prior": 0.9}}
    )

    entry = catalog.resolve_entry("vendor/model-x", provider="openrouter")

    assert entry.source == "user"
    # User-set fields win outright…
    assert entry.context_window == 111
    assert entry.quality_prior == 0.9
    # …while the live layer still fills everything the user left unset.
    assert entry.max_output_tokens == 30_000
    assert entry.display_name == "Vendor Model X"
    assert entry.supports_reasoning is True
    assert entry.supports_vision is True
    assert entry.reasoning_format == "openrouter"


def test_live_beats_corrections_and_corrections_fill_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = ModelCatalog()
    catalog._populate_from_data(
        [
            {
                "id": "vendor/model-y",
                "context_length": 100_000,
                "top_provider": {"max_completion_tokens": 2_048},
                "supported_parameters": ["tools"],
            }
        ]
    )
    _install_corrections(
        monkeypatch,
        """
        [openrouter."vendor/model-y"]
        max_output_tokens = 9999
        supports_reasoning = true
        reasoning_format = "deepseek"
        quality_prior = 0.5
        """,
    )

    entry = catalog.resolve_entry("vendor/model-y", provider="openrouter")

    assert entry.source == "live"
    # Live knows these — the correction must NOT override them…
    assert entry.max_output_tokens == 2_048
    assert entry.supports_reasoning is False
    # …but fields live left unset are filled from corrections.
    assert entry.reasoning_format == "deepseek"
    assert entry.quality_prior == 0.5


def test_corrections_beat_snapshot_and_snapshot_fills_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_corrections(
        monkeypatch,
        """
        [openai."gpt-4"]
        context_window = 7777
        supports_vision = true
        """,
    )

    entry = ModelCatalog().resolve_entry("gpt-4", provider="openai")

    assert entry.source == "corrections"
    assert entry.context_window == 7_777  # corrections beat snapshot's 8192
    assert entry.supports_vision is True  # corrections beat snapshot's False
    assert entry.max_output_tokens == 8_192  # snapshot fills unset fields
    assert entry.supports_tools is True
    assert entry.supports_reasoning is False


def test_snapshot_beats_synthesized_but_floor_fills_gaps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A correction that carries only metadata still gets the synthesized
    # budget floor for the numeric fields nothing knows.
    _install_corrections(
        monkeypatch,
        """
        [zhipu."glm-9-experimental"]
        family = "glm"
        """,
    )

    entry = ModelCatalog().resolve_entry("glm-9-experimental", provider="zhipu")

    assert entry.source == "corrections"
    assert entry.family == "glm"
    assert entry.context_window == 32_768
    assert entry.max_output_tokens == 8_192


# ---------------------------------------------------------------------------
# Glob corrections matching
# ---------------------------------------------------------------------------


def test_glob_corrections_match_lowercased_model_and_exact_key_wins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_corrections(
        monkeypatch,
        """
        [zhipu."glm-9-pro"]
        display_name = "Exact GLM-9 Pro"
        context_window = 123456

        [zhipu."glm-9*"]
        display_name = "Glob GLM-9"
        max_output_tokens = 4242
        supports_reasoning = true
        """,
    )
    catalog = ModelCatalog()

    # Uppercase spelling still matches: model ids are lowercased for lookup.
    exact = catalog.resolve_entry("GLM-9-Pro", provider="zhipu")
    assert exact.display_name == "Exact GLM-9 Pro"  # exact key beats the glob
    assert exact.context_window == 123_456
    assert exact.max_output_tokens == 4_242  # glob fills what exact left unset
    assert exact.supports_reasoning is True

    globbed = catalog.resolve_entry("glm-9-mini", provider="zhipu")
    assert globbed.source == "corrections"
    assert globbed.display_name == "Glob GLM-9"
    assert globbed.context_window == 32_768  # synthesized floor fills the rest

    # Corrections are provider-scoped: same model id, other provider → none.
    other = catalog.resolve_entry("glm-9-mini", provider="openai")
    assert other.source == "synthesized"
    assert other.display_name == ""


def test_corrections_drop_unknown_and_mistyped_fields() -> None:
    tables = model_catalog_module._normalize_corrections(
        {
            "vendor": {
                "model-z": {
                    "context_window": 5_000,
                    "supports_reasoning": "true",  # string, not bool → dropped
                    "bogus_field": 1,  # unknown → dropped
                }
            }
        }
    )

    assert tables == {"vendor": {"model-z": {"context_window": 5_000}}}


def test_packaged_corrections_file_parses_and_is_empty() -> None:
    text = (
        resources.files("opensquilla.provider")
        .joinpath("catalog_overrides.toml")
        .read_text(encoding="utf-8")
    )
    # Bootstrapped with schema docs only — parses cleanly, no data rows yet.
    assert tomllib.loads(text) == {}
    assert isinstance(model_catalog_module._corrections_tables(), dict)


# ---------------------------------------------------------------------------
# Live-layer cost adaptation (per-1k cache → per-Mtok canonical)
# ---------------------------------------------------------------------------


def test_live_costs_adapt_per_1k_to_per_mtok() -> None:
    entry = _populated_catalog().resolve_entry("vendor/model-x", provider="openrouter")

    # OpenRouter per-token "0.0000025" → cached 0.0025/1k → canonical 2.5/Mtok.
    assert entry.input_cost_per_mtok == pytest.approx(2.5)
    assert entry.output_cost_per_mtok == pytest.approx(10.0)


def test_live_zero_price_stays_unknown_not_free() -> None:
    catalog = ModelCatalog()
    catalog._populate_from_data([{"id": "vendor/free-model", "context_length": 8_192}])

    entry = catalog.resolve_entry("vendor/free-model", provider="openrouter")

    # The live cache's 0.0 means "free or unknown" — never claim a known $0.
    assert entry.input_cost_per_mtok is None
    assert entry.output_cost_per_mtok is None


# ---------------------------------------------------------------------------
# User overrides — keying and validation
# ---------------------------------------------------------------------------


def test_user_override_qualified_key_beats_bare_key_per_field() -> None:
    catalog = ModelCatalog()
    catalog.set_user_overrides(
        {
            "deepseek/some-model": {"context_window": 1_000},
            "Some-Model": {"context_window": 2_000, "max_output_tokens": 500},
        }
    )

    qualified = catalog.resolve_entry("some-model", provider="deepseek")
    assert qualified.context_window == 1_000  # qualified key wins the field
    assert qualified.max_output_tokens == 500  # bare key fills what it left unset

    bare = catalog.resolve_entry("some-model")
    assert bare.context_window == 2_000


def test_set_user_overrides_rejects_unknown_fields_and_bad_types() -> None:
    catalog = ModelCatalog()
    catalog.set_user_overrides({"kept-model": {"context_window": 4_096}})

    with pytest.raises(ValueError, match="bogus_field"):
        catalog.set_user_overrides({"m": {"bogus_field": 1}})
    with pytest.raises(ValueError, match="context_window"):
        catalog.set_user_overrides({"m": {"context_window": "big"}})
    with pytest.raises(ValueError, match="supports_tools"):
        catalog.set_user_overrides({"m": {"supports_tools": "false"}})
    # Identity / derived fields are not overridable.
    with pytest.raises(ValueError, match="source"):
        catalog.set_user_overrides({"m": {"source": "user"}})

    # A rejected replacement leaves the previous overrides installed.
    assert catalog.resolve_entry("kept-model").context_window == 4_096


def test_explicit_false_and_zero_overrides_win() -> None:
    catalog = _populated_catalog()
    catalog.set_user_overrides(
        {"vendor/model-x": {"supports_reasoning": False, "max_output_tokens": 0}}
    )

    entry = catalog.resolve_entry("vendor/model-x", provider="openrouter")

    # Presence in a layer = knowledge: False/0 beat the live layer's values.
    assert entry.supports_reasoning is False
    assert entry.max_output_tokens == 0


# ---------------------------------------------------------------------------
# PARITY NET — the legacy resolve paths must keep returning today's exact
# values (captured as literals from the pre-change tree). resolve_entry is a
# parallel substrate; any drift here is an accidental behavior change.
# ---------------------------------------------------------------------------

# (model, provider) → (resolve_max_tokens, resolve_context_window)
_LEGACY_LIMITS: dict[tuple[str, str], tuple[int, int]] = {
    ("gpt-5.5", "openai"): (128_000, 1_050_000),
    ("gpt-5.4-mini", "openai"): (128_000, 400_000),
    ("deepseek-v4-pro", "deepseek"): (384_000, 1_000_000),
    ("kimi-k2.5", "moonshot"): (8_192, 262_144),
    ("glm-5", "zhipu"): (131_072, 204_800),
    ("glm-5", "zai"): (16_384, 202_752),
    ("z-ai/glm-5.2", ""): (32_768, 1_000_000),
    ("gemini-3.5-flash", "gemini"): (65_536, 1_048_576),
    ("minimax-m2.7", ""): (131_072, 204_800),
    ("step-3.5-flash", ""): (16_384, 256_000),
    ("moonshot-v1-32k", "moonshot"): (8_192, 32_768),
    ("grok-4.3", ""): (16_384, 1_000_000),
    ("totally-unknown-model", ""): (16_384, 200_000),
    ("mystery-local", "ollama"): (8_192, 8_192),
    ("some-cloud-model", "openai"): (16_384, 200_000),
}

# (model, provider, base_url) →
#   (supports_reasoning, supports_tools, supports_vision, reasoning_format)
_LEGACY_CAPS: dict[tuple[str, str, str], tuple[bool, bool, bool, str]] = {
    ("claude-opus-4.8", "anthropic", ""): (False, True, False, "none"),
    ("llama3.2:3b", "ollama", ""): (False, True, False, "none"),
    ("gpt-5.5", "openai", "https://api.openai.com/v1"): (True, True, False, "openai"),
    ("deepseek-v4-pro", "deepseek", ""): (True, True, False, "deepseek"),
    ("glm-5", "zhipu", ""): (True, True, False, "zai"),
    ("glm-4.6", "zhipu", ""): (False, True, False, "none"),
    ("qwen3-coder-plus", "dashscope", ""): (True, True, False, "dashscope"),
    ("kimi-k2.5", "moonshot", ""): (True, True, True, "moonshot"),
    ("gemini-3.5-flash", "gemini", ""): (False, True, True, "none"),
    ("doubao-seed-1-6-251015", "volcengine", ""): (True, True, True, "volcengine"),
    ("totally-unknown-model", "openrouter", ""): (False, True, False, "none"),
    ("gpt-4", "openai", ""): (False, True, False, "none"),
}


def test_parity_legacy_limits_unchanged() -> None:
    catalog = ModelCatalog()
    for (model, provider), (max_tokens, context_window) in _LEGACY_LIMITS.items():
        assert catalog.resolve_max_tokens(model, provider=provider) == max_tokens, (
            model,
            provider,
        )
        assert catalog.resolve_context_window(model, provider) == context_window, (
            model,
            provider,
        )


def test_parity_legacy_capabilities_unchanged() -> None:
    catalog = ModelCatalog()
    for (model, provider, base_url), expected in _LEGACY_CAPS.items():
        caps = catalog.get_capabilities(model, provider_name=provider, base_url=base_url)
        observed = (
            caps.supports_reasoning,
            caps.supports_tools,
            caps.supports_vision,
            caps.reasoning_format,
        )
        assert observed == expected, (model, provider, base_url)
