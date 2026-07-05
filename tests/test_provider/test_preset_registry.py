"""Preset registry: packaged data parity, synthesized coverage, and API shape.

The golden fixture (``golden/router_tier_profiles.json``) was captured from
``git show staging/provider-overhaul:src/opensquilla/gateway/config.py``
(``_router_tier_profile_defaults`` at f884d4c9) and pins the packaged preset
data byte-identically to the historical hardcoded dict literals.
"""

from __future__ import annotations

import json
from pathlib import Path

from opensquilla.provider.preset_registry import (
    LEGACY_PROVIDER_PRESET_IDS,
    ProviderPreset,
    get_preset,
    legacy_profile_ids,
    list_presets,
)
from opensquilla.provider.registry import list_provider_specs

GOLDEN_PATH = Path(__file__).parent / "golden" / "router_tier_profiles.json"
LEGACY_NINE = frozenset(
    {
        "openrouter",
        "dashscope",
        "deepseek",
        "gemini",
        "volcengine",
        "byteplus",
        "openai",
        "zhipu",
        "moonshot",
    }
)
TEXT_TIERS = ("c0", "c1", "c2", "c3")


def _golden() -> dict[str, dict]:
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))


# --- packaged presets -------------------------------------------------------


def test_legacy_profile_ids_equal_the_literal_nine() -> None:
    assert legacy_profile_ids() == LEGACY_NINE
    assert LEGACY_PROVIDER_PRESET_IDS == LEGACY_NINE


def test_non_synthesized_registry_ids_equal_the_literal_nine() -> None:
    packaged = list_presets(include_synthesized=False)
    assert frozenset(p.preset_id for p in packaged) == LEGACY_NINE
    assert all(not p.synthesized for p in packaged)


def test_packaged_presets_match_golden_tier_data_exactly() -> None:
    golden = _golden()
    assert frozenset(golden) == LEGACY_NINE
    for preset_id, tiers in golden.items():
        preset = get_preset(preset_id)
        assert preset is not None, preset_id
        assert preset.synthesized is False
        assert preset.tier_defaults() == tiers, preset_id


def test_packaged_preset_id_equals_provider_id() -> None:
    # Recorded decision: preset_id == provider_id this cycle.
    for preset in list_presets():
        assert preset.preset_id == preset.provider_id


def test_packaged_preset_metadata_is_populated() -> None:
    for preset_id in sorted(LEGACY_NINE):
        preset = get_preset(preset_id)
        assert preset is not None
        assert preset.label
        assert preset.description
        assert preset.default_model


def test_packaged_default_model_follows_onboarding_direct_default() -> None:
    # default_model mirrors onboarding's default-direct-model semantics:
    # the c1 tier model (c0 fallback) for curated profiles.
    golden = _golden()
    for preset_id in sorted(LEGACY_NINE):
        preset = get_preset(preset_id)
        assert preset is not None
        tiers = golden[preset_id]
        expected = str((tiers.get("c1") or tiers.get("c0") or {}).get("model") or "")
        assert preset.default_model == expected, preset_id


def test_only_openrouter_packages_an_image_tier() -> None:
    for preset_id in sorted(LEGACY_NINE):
        preset = get_preset(preset_id)
        assert preset is not None
        if preset_id == "openrouter":
            assert "image_model" in preset.tiers
        else:
            assert "image_model" not in preset.tiers


def test_tier_defaults_returns_fresh_copies() -> None:
    preset = get_preset("openai")
    assert preset is not None
    first = preset.tier_defaults()
    first["c0"]["model"] = "mutated"
    first["extra"] = {}
    assert preset.tier_defaults()["c0"]["model"] != "mutated"
    assert "extra" not in preset.tier_defaults()


# --- synthesized presets ----------------------------------------------------


def test_every_runtime_provider_has_a_preset() -> None:
    runtime_ids = {s.provider_id for s in list_provider_specs() if s.runtime_supported}
    registry_ids = {p.preset_id for p in list_presets()}
    assert runtime_ids <= registry_ids


def test_non_runtime_providers_have_no_synthesized_preset() -> None:
    non_runtime = {s.provider_id for s in list_provider_specs() if not s.runtime_supported}
    synthesized_ids = {p.preset_id for p in list_presets() if p.synthesized}
    assert not (non_runtime & synthesized_ids)


def test_synthesized_presets_bind_all_text_tiers_to_provider_default() -> None:
    synthesized = [p for p in list_presets() if p.synthesized]
    assert synthesized, "expected at least one synthesized preset"
    for preset in synthesized:
        assert preset.preset_id not in LEGACY_NINE
        # Onboarding's direct default model is empty for non-curated providers.
        assert preset.default_model == ""
        assert set(preset.tiers) == set(TEXT_TIERS)
        assert "image_model" not in preset.tiers
        for tier in TEXT_TIERS:
            entry = preset.tiers[tier]
            assert entry["provider"] == preset.provider_id
            assert entry["model"] == preset.default_model
            assert entry["description"]
            assert entry["supports_image"] is False


def test_synthesized_ids_are_never_legacy_profile_ids() -> None:
    # Registry-only objects: a synthesized id must never become a valid
    # persisted tier_profile (rc1 bricks on unknown ids).
    for preset in list_presets():
        if preset.synthesized:
            assert preset.preset_id not in legacy_profile_ids()


# --- lookup API -------------------------------------------------------------


def test_get_preset_normalizes_case_and_whitespace() -> None:
    preset = get_preset("  OpenAI  ")
    assert preset is not None
    assert preset.preset_id == "openai"


def test_get_preset_unknown_returns_none() -> None:
    assert get_preset("does-not-exist") is None
    assert get_preset("") is None


def test_list_presets_orders_packaged_before_synthesized() -> None:
    presets = list_presets()
    flags = [p.synthesized for p in presets]
    assert flags == sorted(flags)


def test_provider_preset_is_frozen() -> None:
    preset = get_preset("openai")
    assert isinstance(preset, ProviderPreset)
    try:
        preset.label = "nope"  # type: ignore[misc]
    except Exception:
        pass
    else:
        raise AssertionError("ProviderPreset must be frozen")
