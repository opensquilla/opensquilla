"""Contract tests for the vendored models.dev snapshot lookups."""

from __future__ import annotations

from opensquilla.provider.models_dev import (
    _snapshot_providers,
    lookup_limits,
    lookup_model,
)


def test_snapshot_loads_and_covers_registered_providers() -> None:
    providers = _snapshot_providers()
    assert providers, "vendored snapshot must load"
    for expected in ("openrouter", "openai", "anthropic", "deepseek", "gemini", "zhipu"):
        assert expected in providers, f"snapshot missing provider table: {expected}"


def test_provider_scoped_lookup_prefers_own_table() -> None:
    entry = lookup_model("deepseek", "deepseek-v4-pro")
    assert entry is not None
    assert entry["ctx"] == 1_000_000
    assert entry["out"] == 384_000
    assert entry["reasoning"] is True
    assert entry["tools"] is True


def test_basename_fallback_within_provider_table() -> None:
    # OpenRouter spelling against the direct-provider table resolves via
    # basename, so both spellings agree.
    qualified = lookup_limits("deepseek", "deepseek/deepseek-v4-pro")
    bare = lookup_limits("deepseek", "deepseek-v4-pro")
    assert qualified == bare


def test_cross_provider_merge_is_conservative() -> None:
    # No provider table for "" → merge across providers with per-dimension min.
    merged = lookup_model("", "deepseek-v4-pro")
    assert merged is not None
    scoped_openrouter = lookup_model("openrouter", "deepseek/deepseek-v4-pro")
    scoped_direct = lookup_model("deepseek", "deepseek-v4-pro")
    assert scoped_openrouter is not None and scoped_direct is not None
    assert merged["ctx"] <= min(scoped_openrouter["ctx"], scoped_direct["ctx"])


def test_case_insensitive_lookup() -> None:
    # MiniMax publishes mixed-case ids; snapshot keys and lookups are lowercase.
    assert lookup_model("minimax", "MiniMax-M2.5") is not None


def test_unknown_model_returns_none() -> None:
    assert lookup_model("openai", "no-such-model-xyz") is None
    assert lookup_limits("openai", "no-such-model-xyz") is None
    assert lookup_model("", "") is None
