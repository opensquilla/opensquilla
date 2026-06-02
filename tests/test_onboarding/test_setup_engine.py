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
