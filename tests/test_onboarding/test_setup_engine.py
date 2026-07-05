"""Tests for the shared onboarding setup engine."""

import tomllib

from opensquilla.onboarding.setup_engine import SetupEngine


def test_setup_engine_applies_provider_and_router_without_persisting_secret(tmp_path):
    target = tmp_path / "config.toml"
    engine = SetupEngine(path=target)

    engine.apply(
        "provider",
        {
            "providerId": "deepseek",
            "model": "deepseek-chat",
            "apiKeyEnv": "DEEPSEEK_API_KEY",
        },
    )
    engine.apply("router", {"mode": "recommended"})
    result = engine.persist()

    data = tomllib.loads(target.read_text())
    assert result.path == target
    assert data["llm"]["provider"] == "deepseek"
    assert data["llm"]["api_key_env"] == "DEEPSEEK_API_KEY"
    assert "api_key" not in data["llm"]
    assert data["squilla_router"]["tier_profile"] == "deepseek"
    assert "tiers" not in data["squilla_router"]


def test_setup_engine_can_derive_provider_model_from_router_default_tier(tmp_path):
    target = tmp_path / "config.toml"
    engine = SetupEngine(path=target)

    engine.apply(
        "provider",
        {
            "providerId": "deepseek",
            "apiKeyEnv": "DEEPSEEK_API_KEY",
        },
    )
    result = engine.persist()

    data = tomllib.loads(target.read_text())
    assert result.path == target
    assert data["llm"]["provider"] == "deepseek"
    assert data["llm"]["model"] == "deepseek-v4-flash"
    assert data["squilla_router"]["tier_profile"] == "deepseek"
    assert data["squilla_router"]["default_tier"] == "c1"


def test_setup_engine_passes_preset_id_through_to_provider_upsert(tmp_path):
    # The CLI's --preset flag rides this payload key; a synthesized preset
    # must persist the custom-mode shape (no tier_profile, expanded tiers).
    target = tmp_path / "config.toml"
    engine = SetupEngine(path=target)

    engine.apply(
        "provider",
        {
            "providerId": "groq",
            "model": "llama-3.3-70b",
            "apiKeyEnv": "GROQ_API_KEY",
            "presetId": "groq",
        },
    )
    engine.persist()

    data = tomllib.loads(target.read_text())
    assert data["llm"]["provider"] == "groq"
    assert data["squilla_router"]["enabled"] is True
    assert "tier_profile" not in data["squilla_router"]
    tier = data["squilla_router"]["tiers"]["c0"]
    assert tier["provider"] == "groq"
    assert tier["model"] == "llama-3.3-70b"


def test_setup_engine_router_tier_override_updates_direct_fallback_model(tmp_path):
    target = tmp_path / "config.toml"
    engine = SetupEngine(path=target)

    engine.apply(
        "provider",
        {
            "providerId": "openai",
            "apiKeyEnv": "OPENAI_API_KEY",
        },
    )
    engine.apply(
        "router",
        {
            "mode": "recommended",
            "defaultTier": "c2",
            "tiers": {
                "c2": {
                    "provider": "openai",
                    "model": "gpt-5.5-custom",
                    "thinkingLevel": "high",
                }
            },
        },
    )
    engine.persist()

    data = tomllib.loads(target.read_text())
    assert data["llm"]["model"] == "gpt-5.5-custom"
    assert data["squilla_router"]["tier_profile"] == "openai"
    assert data["squilla_router"]["default_tier"] == "c2"
    assert data["squilla_router"]["tiers"]["c2"]["model"] == "gpt-5.5-custom"
    assert data["squilla_router"]["tiers"]["c2"]["thinking_level"] == "high"


def test_setup_engine_next_steps_do_not_include_secret(tmp_path):
    engine = SetupEngine(path=tmp_path / "config.toml")
    engine.apply(
        "provider",
        {
            "providerId": "openrouter",
            "model": "deepseek/deepseek-v4-flash",
            "apiKey": "sk-secret",
        },
    )

    text = engine.preview_next_steps()

    assert "sk-secret" not in text
    assert "opensquilla gateway start" in text
    assert "openrouter" in text


def test_setup_engine_image_generation_can_use_custom_env_reference(
    tmp_path,
    monkeypatch,
):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("OPENSQUILLA_TEST_IMAGE_KEY", "sk-image-env")
    target = tmp_path / "config.toml"
    engine = SetupEngine(path=target)

    engine.apply(
        "image-generation",
        {
            "providerId": "openrouter",
            "primary": "openrouter/google/gemini-3.1-flash-image-preview",
            "apiKeyEnv": "OPENSQUILLA_TEST_IMAGE_KEY",
        },
    )
    engine.persist()

    data = tomllib.loads(target.read_text())
    provider = data["image_generation"]["providers"]["openrouter"]
    assert provider["api_key"] == ""
    assert provider["api_key_env"] == "OPENSQUILLA_TEST_IMAGE_KEY"


def test_setup_engine_accepts_short_capability_section_aliases(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    target = tmp_path / "config.toml"
    engine = SetupEngine(path=target)

    engine.apply("image", {"enabled": False})
    engine.apply(
        "memory",
        {
            "providerId": "local",
            "onnxDir": "models/bge",
        },
    )
    engine.persist()

    data = tomllib.loads(target.read_text())
    assert data["image_generation"]["enabled"] is False
    assert data["memory"]["embedding"]["provider"] == "local"
    assert data["memory"]["embedding"]["local"]["onnx_dir"] == "models/bge"


def test_setup_engine_catalog_includes_memory_embedding():
    engine = SetupEngine()

    payload = engine.catalog("memory-embedding")

    provider_ids = {p["providerId"] for p in payload["memoryEmbeddingProviders"]}
    assert {"auto", "local", "openai", "ollama", "none"} <= provider_ids
    assert all("whatYouNeed" in p for p in payload["memoryEmbeddingProviders"])


def test_setup_engine_applies_ensemble_with_keep_current_semantics(tmp_path):
    import pytest

    target = tmp_path / "config.toml"
    engine = SetupEngine(path=target)
    engine.apply(
        "ensemble",
        {
            "enabled": True,
            "selectionMode": "router_dynamic",
            "modelOptions": ["prov/model-a", "prov/model-b"],
            "minSuccessfulProposers": 2,
            "allFailedPolicy": "error",
        },
    )
    engine.persist()

    data = tomllib.loads(target.read_text())
    ensemble = data["llm_ensemble"]
    assert ensemble["enabled"] is True
    assert ensemble["selection_mode"] == "router_dynamic"
    assert ensemble["model_options"] == ["prov/model-a", "prov/model-b"]
    assert ensemble["min_successful_proposers"] == 2
    assert ensemble["all_failed_policy"] == "error"

    # A partial payload must only touch the keys it names.
    second = SetupEngine(path=target)
    second.apply("ensemble", {"enabled": False})
    second.persist()

    data = tomllib.loads(target.read_text())
    ensemble = data["llm_ensemble"]
    assert ensemble["enabled"] is False
    assert ensemble["selection_mode"] == "router_dynamic"
    assert ensemble["model_options"] == ["prov/model-a", "prov/model-b"]
    assert ensemble["min_successful_proposers"] == 2
    assert ensemble["all_failed_policy"] == "error"

    with pytest.raises(ValueError, match="modelOptions must be a list"):
        SetupEngine(path=target).apply("ensemble", {"modelOptions": "not-a-list"})


def test_setup_engine_accepts_ensemble_section_aliases(tmp_path):
    for alias in ("ensemble", "llm-ensemble", "llm_ensemble"):
        target = tmp_path / f"{alias.replace('_', '-')}.toml"
        engine = SetupEngine(path=target)
        engine.apply(alias, {"enabled": False})
        engine.persist()
        data = tomllib.loads(target.read_text())
        assert data["llm_ensemble"]["enabled"] is False
