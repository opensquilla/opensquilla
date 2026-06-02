"""Tests for onboarding mutations."""

from __future__ import annotations

import pytest

from opensquilla.gateway.config import GatewayConfig
from opensquilla.gateway.llm_runtime import resolve_llm_runtime_config
from opensquilla.onboarding.mutations import (
    MutationResult,
    list_channel_entries,
    remove_channel,
    set_channel_enabled,
    upsert_channel,
    upsert_image_generation_provider,
    upsert_llm_provider,
    upsert_memory_embedding,
    upsert_router,
    upsert_search_provider,
    validate_channel_entry,
)
from opensquilla.onboarding.redaction import REDACTED_PLACEHOLDER


def test_upsert_provider_persists_fields():
    cfg = GatewayConfig()
    res = upsert_llm_provider(
        cfg,
        provider_id="openrouter",
        model="deepseek/deepseek-v4-flash",
        api_key="sk-test",
        base_url="https://openrouter.ai/api/v1",
    )
    assert isinstance(res, MutationResult)
    assert res.config.llm.provider == "openrouter"
    assert res.config.llm.model == "deepseek/deepseek-v4-flash"
    assert res.config.llm.api_key == "sk-test"
    assert res.changed is True


def test_upsert_provider_strips_trailing_paste_punctuation_from_api_key():
    cfg = GatewayConfig()
    res = upsert_llm_provider(
        cfg,
        provider_id="openrouter",
        model="deepseek/deepseek-v4-flash",
        api_key="sk-test、",
    )

    assert res.config.llm.api_key == "sk-test"


def test_provider_payload_redacts_api_key():
    cfg = GatewayConfig()
    res = upsert_llm_provider(cfg, provider_id="openrouter", model="x", api_key="sk-test")
    assert res.public_payload["api_key"] == REDACTED_PLACEHOLDER


def test_upsert_memory_embedding_local_requires_restart():
    cfg = GatewayConfig()
    res = upsert_memory_embedding(
        cfg,
        provider="local",
        model="BAAI/bge-small-zh-v1.5",
        onnx_dir="models/bge",
    )
    assert res.restart_required is True
    assert res.config.memory.embedding.requested_provider == "local"
    assert res.config.memory.embedding.local.onnx_dir == "models/bge"


def test_upsert_memory_embedding_remote_redacts_key():
    cfg = GatewayConfig()
    res = upsert_memory_embedding(
        cfg,
        provider="openai",
        model="text-embedding-3-small",
        api_key="mem-secret",
        base_url="https://api.openai.com/v1",
    )
    assert res.config.memory.embedding.remote.api_key == "mem-secret"
    assert res.public_payload["remote"]["api_key"] == REDACTED_PLACEHOLDER


def test_upsert_memory_embedding_remote_can_use_env_key_reference():
    cfg = GatewayConfig()
    res = upsert_memory_embedding(
        cfg,
        provider="openai",
        model="text-embedding-3-small",
        api_key_env="OPENAI_EMBEDDINGS_API_KEY",
        base_url="https://api.openai.com/v1",
    )

    remote = res.config.memory.embedding.remote
    assert remote.api_key in {"", None}
    assert remote.api_key_env == "OPENAI_EMBEDDINGS_API_KEY"
    assert res.public_payload["remote"]["api_key_env"] == "OPENAI_EMBEDDINGS_API_KEY"


def test_upsert_memory_embedding_auto_can_store_remote_fallback():
    cfg = GatewayConfig()
    res = upsert_memory_embedding(
        cfg,
        provider="auto",
        model="text-embedding-3-small",
        api_key="mem-secret",
        base_url="https://embeddings.example/v1",
    )
    assert res.config.memory.embedding.requested_provider == "auto"
    assert res.config.memory.embedding.remote.api_key == "mem-secret"
    assert res.config.memory.embedding.remote.base_url == "https://embeddings.example/v1"
    assert res.config.memory.embedding.remote.model == "text-embedding-3-small"
    assert res.public_payload["remote"]["api_key"] == REDACTED_PLACEHOLDER


def test_upsert_memory_embedding_explicit_remote_reuses_auto_remote_key():
    cfg = GatewayConfig(
        memory={
            "embedding": {
                "provider": "auto",
                "remote": {
                    "api_key": "mem-secret",
                    "base_url": "https://embeddings.example/v1",
                    "model": "embed-model",
                },
            }
        }
    )
    res = upsert_memory_embedding(cfg, provider="openai", api_key="")
    assert res.config.memory.embedding.requested_provider == "openai"
    assert res.config.memory.embedding.remote.api_key == "mem-secret"
    assert res.config.memory.embedding.remote.base_url == "https://embeddings.example/v1"
    assert res.config.memory.embedding.remote.model == "embed-model"


def test_upsert_memory_embedding_auto_without_changes_does_not_require_restart():
    cfg = GatewayConfig()
    res = upsert_memory_embedding(cfg, provider="auto")
    assert res.changed is False
    assert res.restart_required is False


def test_unsupported_provider_rejected():
    cfg = GatewayConfig()
    with pytest.raises(ValueError, match="not runtime-supported"):
        upsert_llm_provider(cfg, provider_id="openai_codex", model="x")


def test_unverified_base_url_provider_rejected_before_configuration():
    cfg = GatewayConfig()
    with pytest.raises(ValueError, match="not runtime-supported"):
        upsert_llm_provider(cfg, provider_id="azure", model="x", api_key="k")


def test_ollama_does_not_require_api_key():
    cfg = GatewayConfig()
    res = upsert_llm_provider(cfg, provider_id="ollama", model="llama3.1")
    assert res.changed is True
    assert res.config.llm.provider == "ollama"


def test_upsert_channel_appends_new():
    cfg = GatewayConfig()
    res = upsert_channel(
        cfg,
        entry_payload={
            "type": "slack",
            "name": "work",
            "token": "xoxb-secret",
            "signing_secret": "ss-secret",
        },
    )
    assert res.restart_required is True
    entries = list_channel_entries(res.config)
    assert len(entries) == 1
    assert entries[0]["name"] == "work"
    assert entries[0]["type"] == "slack"


def test_upsert_channel_updates_same_name():
    cfg = GatewayConfig()
    res1 = upsert_channel(
        cfg,
        entry_payload={
            "type": "slack",
            "name": "work",
            "token": "old",
            "signing_secret": "ss-old",
        },
    )
    res2 = upsert_channel(
        res1.config,
        entry_payload={"type": "slack", "name": "work", "token": "new", "slack_channel_id": "C123"},
    )
    entries = list_channel_entries(res2.config)
    assert len(entries) == 1
    assert entries[0]["slack_channel_id"] == "C123"


def test_upsert_channel_redacts_secrets_in_payload():
    cfg = GatewayConfig()
    res = upsert_channel(
        cfg,
        entry_payload={"type": "telegram", "name": "tg", "token": "abc"},
    )
    assert res.public_payload["token"] == REDACTED_PLACEHOLDER


def test_slack_webhook_channel_requires_signing_secret():
    cfg = GatewayConfig()
    with pytest.raises(ValueError, match="signing_secret"):
        upsert_channel(
            cfg,
            entry_payload={"type": "slack", "name": "w", "token": "xoxb-test"},
        )


def test_slack_socket_channel_does_not_require_signing_secret():
    cfg = GatewayConfig()
    res = upsert_channel(
        cfg,
        entry_payload={
            "type": "slack",
            "name": "w",
            "token": "xoxb-test",
            "connection_mode": "socket",
            "app_token": "xapp-test",
        },
    )

    entry = list_channel_entries(res.config)[0]
    assert entry["connection_mode"] == "socket"
    assert "signing_secret" not in entry or entry["signing_secret"] in (None, "")


def test_slack_socket_channel_requires_app_token():
    cfg = GatewayConfig()
    with pytest.raises(ValueError, match="app_token"):
        upsert_channel(
            cfg,
            entry_payload={
                "type": "slack",
                "name": "w",
                "token": "xoxb-test",
                "connection_mode": "socket",
            },
        )


def test_remove_channel():
    cfg = GatewayConfig()
    res1 = upsert_channel(
        cfg,
        entry_payload={"type": "slack", "name": "w", "token": "x", "signing_secret": "ss"},
    )
    res2 = remove_channel(res1.config, name="w")
    assert list_channel_entries(res2.config) == []
    assert res2.restart_required is True


def test_remove_missing_channel_raises():
    cfg = GatewayConfig()
    with pytest.raises(KeyError, match="w"):
        remove_channel(cfg, name="w")


def test_set_channel_enabled_toggles():
    cfg = GatewayConfig()
    res1 = upsert_channel(
        cfg,
        entry_payload={"type": "slack", "name": "w", "token": "x", "signing_secret": "ss"},
    )
    res2 = set_channel_enabled(res1.config, name="w", enabled=False)
    assert list_channel_entries(res2.config)[0]["enabled"] is False


def test_invalid_channel_type_rejected():
    cfg = GatewayConfig()
    with pytest.raises(ValueError, match="unknown channel type"):
        upsert_channel(cfg, entry_payload={"type": "nope", "name": "x"})


def test_telegram_webhook_requires_webhook_url():
    cfg = GatewayConfig()
    with pytest.raises(ValueError, match="webhook_url"):
        upsert_channel(
            cfg,
            entry_payload={
                "type": "telegram",
                "name": "t",
                "token": "x",
                "transport_name": "webhook",
            },
        )


def test_upsert_llm_provider_preserves_existing_api_key_on_same_provider():
    cfg = GatewayConfig()
    res1 = upsert_llm_provider(
        cfg,
        provider_id="openrouter",
        model="m1",
        api_key="sk-existing",
        base_url="https://openrouter.ai/api/v1",
    )
    # Reconfigure model only, leaving api_key blank — should reuse existing.
    res2 = upsert_llm_provider(
        res1.config,
        provider_id="openrouter",
        model="m2",
        api_key="",
    )
    assert res2.config.llm.api_key == "sk-existing"
    assert res2.config.llm.model == "m2"


def test_upsert_llm_provider_can_use_env_key_without_secret():
    cfg = GatewayConfig()
    res = upsert_llm_provider(
        cfg,
        provider_id="openrouter",
        model="deepseek/deepseek-v4-flash",
        api_key="",
        api_key_env="OPENROUTER_API_KEY",
    )

    assert res.config.llm.api_key == ""
    assert res.config.llm.api_key_env == "OPENROUTER_API_KEY"
    assert res.public_payload["api_key_source"] == "env"


def test_upsert_llm_provider_recomputes_openrouter_mix_on_provider_switch():
    cfg = GatewayConfig(llm={"provider": "openrouter", "model": "deepseek/x"})
    assert cfg.squilla_router.enabled is True
    assert cfg.squilla_router.tier_profile is None

    res = upsert_llm_provider(
        cfg,
        provider_id="deepseek",
        model="deepseek-chat",
        api_key_env="DEEPSEEK_API_KEY",
    )

    assert res.config.llm.provider == "deepseek"
    assert res.config.squilla_router.enabled is True
    assert res.config.squilla_router.tier_profile == "deepseek"
    assert res.config.squilla_router.tiers["t0"]["provider"] == "deepseek"
    assert "tiers" not in res.config.to_toml_dict()["squilla_router"]


def test_upsert_router_recommended_writes_profile_without_expanded_tiers():
    cfg = GatewayConfig(llm={"provider": "deepseek", "model": "deepseek-chat"})

    res = upsert_router(cfg, mode="recommended")

    assert res.config.squilla_router.enabled is True
    assert res.config.squilla_router.tier_profile == "deepseek"
    assert "tiers" not in res.config.to_toml_dict()["squilla_router"]
    assert res.public_payload["mode"] == "recommended"


def test_upsert_router_can_disable():
    cfg = GatewayConfig(llm={"provider": "openrouter", "model": "deepseek/x"})

    res = upsert_router(cfg, mode="disabled")

    assert res.config.squilla_router.enabled is False
    assert res.config.squilla_router.tier_profile is None
    assert res.public_payload["mode"] == "disabled"


def test_upsert_router_rejects_openrouter_mix_for_direct_provider():
    cfg = GatewayConfig(llm={"provider": "deepseek", "model": "deepseek-chat"})

    with pytest.raises(ValueError, match="openrouter-mix"):
        upsert_router(cfg, mode="openrouter-mix")


def test_upsert_llm_provider_keeps_runtime_secret_marker_when_reusing_key():
    cfg = GatewayConfig()
    cfg.llm.provider = "openrouter"
    cfg.llm.model = "m1"
    cfg.llm.api_key = "from-env"
    cfg.mark_runtime_secret("llm.api_key")

    res = upsert_llm_provider(
        cfg,
        provider_id="openrouter",
        model="m2",
        api_key="",
    )

    assert res.config.llm.api_key == "from-env"
    assert "llm.api_key" in res.config._runtime_secret_paths


def test_upsert_llm_provider_clears_runtime_secret_marker_for_explicit_key():
    cfg = GatewayConfig()
    cfg.llm.provider = "openrouter"
    cfg.llm.model = "m1"
    cfg.llm.api_key = "from-env"
    cfg.mark_runtime_secret("llm.api_key")

    res = upsert_llm_provider(
        cfg,
        provider_id="openrouter",
        model="m2",
        api_key="sk-written",
    )

    assert res.config.llm.api_key == "sk-written"
    assert "llm.api_key" not in res.config._runtime_secret_paths


def test_upsert_llm_provider_explicit_key_clears_existing_env_key(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "from-env")
    cfg = GatewayConfig(
        llm={
            "provider": "openrouter",
            "model": "m1",
            "api_key": "",
            "api_key_env": "OPENROUTER_API_KEY",
        }
    )

    res = upsert_llm_provider(
        cfg,
        provider_id="openrouter",
        model="m2",
        api_key="sk-written",
    )
    runtime = resolve_llm_runtime_config(res.config)

    assert res.config.llm.api_key_env == ""
    assert runtime.api_key == "sk-written"
    assert runtime.api_key_from_env is False


def test_upsert_llm_provider_rejects_ambiguous_key_sources():
    cfg = GatewayConfig()

    with pytest.raises(ValueError, match="either api_key or api_key_env"):
        upsert_llm_provider(
            cfg,
            provider_id="openrouter",
            model="m",
            api_key="sk-written",
            api_key_env="OPENROUTER_API_KEY",
        )


def test_upsert_llm_provider_does_not_carry_key_across_providers():
    cfg = GatewayConfig()
    res1 = upsert_llm_provider(
        cfg,
        provider_id="openrouter",
        model="m",
        api_key="sk-or",
    )
    # Switching to a different key-required provider must require a new key.
    with pytest.raises(ValueError, match="api_key"):
        upsert_llm_provider(
            res1.config,
            provider_id="openai",
            model="gpt-4o",
            api_key="",
        )


def test_validate_channel_entry_returns_normalized_payload():
    out = validate_channel_entry(
        {"type": "slack", "name": "w", "token": "x", "signing_secret": "ss"}
    )
    assert out["type"] == "slack"
    assert out["enabled"] is True
    assert out["agent_id"] == "main"


def test_upsert_search_provider_configures_brave():
    cfg = GatewayConfig()
    res = upsert_search_provider(
        cfg,
        provider_id="brave",
        api_key="brave-key",
        max_results=7,
        proxy="http://127.0.0.1:7890",
        use_env_proxy=True,
        fallback_policy="network",
        diagnostics=True,
    )
    assert res.config.search_provider == "brave"
    assert res.config.search_api_key == "brave-key"
    assert res.config.search_max_results == 7
    assert res.config.search_proxy == "http://127.0.0.1:7890"
    assert res.config.search_use_env_proxy is True
    assert res.config.search_fallback_policy == "network"
    assert res.config.search_diagnostics is True
    assert res.public_payload["api_key"] == REDACTED_PLACEHOLDER


def test_upsert_search_provider_strips_trailing_paste_punctuation_from_api_key():
    cfg = GatewayConfig()
    res = upsert_search_provider(cfg, provider_id="brave", api_key="brave-key、")

    assert res.config.search_api_key == "brave-key"


def test_upsert_search_provider_can_use_env_key_reference():
    cfg = GatewayConfig()
    res = upsert_search_provider(
        cfg,
        provider_id="brave",
        api_key="",
        api_key_env="BRAVE_SEARCH_API_KEY",
    )
    assert res.config.search_provider == "brave"
    assert res.config.search_api_key == ""
    assert res.config.search_api_key_env == "BRAVE_SEARCH_API_KEY"
    assert res.public_payload["api_key_source"] == "env"


def test_upsert_search_provider_accepts_webui_string_max_results():
    cfg = GatewayConfig()
    res = upsert_search_provider(
        cfg,
        provider_id="duckduckgo",
        max_results="5",
    )

    assert res.config.search_provider == "duckduckgo"
    assert res.config.search_max_results == 5


def test_upsert_search_provider_clears_env_key_for_no_key_provider():
    cfg = GatewayConfig(search_provider="brave", search_api_key_env="BRAVE_SEARCH_API_KEY")

    res = upsert_search_provider(
        cfg,
        provider_id="duckduckgo",
        api_key_env="BRAVE_SEARCH_API_KEY",
    )

    assert res.config.search_provider == "duckduckgo"
    assert res.config.search_api_key_env == ""
    assert res.public_payload["api_key_source"] == "none"


def test_upsert_image_generation_provider_configures_openrouter(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    cfg = GatewayConfig()
    res = upsert_image_generation_provider(
        cfg,
        provider_id="openrouter",
        primary="openrouter/google/gemini-3.1-flash-image-preview",
        api_key="sk-or",
    )
    assert res.config.image_generation.enabled is True
    assert res.config.image_generation.primary == "openrouter/google/gemini-3.1-flash-image-preview"
    assert res.config.image_generation.providers.openrouter.api_key == "sk-or"
    assert res.public_payload["api_key"] == REDACTED_PLACEHOLDER
    assert res.public_payload["api_key_source"] == "explicit"


def test_upsert_image_generation_provider_can_use_matching_llm_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    cfg = GatewayConfig()
    cfg.llm.provider = "openrouter"
    cfg.llm.api_key = "sk-llm"
    res = upsert_image_generation_provider(cfg, provider_id="openrouter")
    assert res.config.image_generation.enabled is True
    assert res.config.image_generation.providers.openrouter.api_key == ""
    assert res.public_payload["api_key_source"] == "llm_fallback"


def test_upsert_image_generation_provider_can_disable_without_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    cfg = GatewayConfig()

    res = upsert_image_generation_provider(
        cfg,
        provider_id="openrouter",
        primary="openrouter/google/gemini-3.1-flash-image-preview",
        enabled=False,
    )

    assert res.config.image_generation.enabled is False
    assert res.config.image_generation.primary == "openrouter/google/gemini-3.1-flash-image-preview"
    assert res.public_payload["api_key_source"] == "none"


def test_upsert_image_generation_provider_rejects_wrong_primary_provider():
    cfg = GatewayConfig()
    cfg.llm.provider = "openrouter"
    cfg.llm.api_key = "sk-llm"
    with pytest.raises(ValueError, match="provider/model"):
        upsert_image_generation_provider(
            cfg,
            provider_id="openrouter",
            primary="openai/gpt-image-1",
        )


def test_search_provider_requiring_key_can_reuse_existing_key():
    cfg = GatewayConfig(search_provider="brave", search_api_key="old")
    res = upsert_search_provider(cfg, provider_id="brave", api_key="")
    assert res.config.search_api_key == "old"


def test_search_provider_requiring_key_rejects_missing_key():
    cfg = GatewayConfig()
    with pytest.raises(ValueError, match="api_key"):
        upsert_search_provider(cfg, provider_id="brave", api_key="", api_key_env="")


def test_unsupported_search_provider_rejected():
    cfg = GatewayConfig()
    with pytest.raises(ValueError, match="not runtime-supported"):
        upsert_search_provider(cfg, provider_id="tavily", api_key="k")


def test_upsert_channel_preserves_secret_when_blank():
    cfg = GatewayConfig()
    first = upsert_channel(
        cfg,
        entry_payload={
            "type": "slack",
            "name": "w",
            "token": "xoxb-original",
            "signing_secret": "ss-original",
        },
    )
    second = upsert_channel(
        first.config,
        entry_payload={
            "type": "slack",
            "name": "w",
            "token": "",  # blank = keep current
            "signing_secret": "",
            "slack_channel_id": "C999",
        },
    )
    raw = [e.model_dump(mode="python") for e in second.config.channels.channels]
    entry = next(e for e in raw if e["name"] == "w")
    assert entry["token"] == "xoxb-original"
    assert entry["signing_secret"] == "ss-original"
    assert entry["slack_channel_id"] == "C999"


def test_upsert_channel_replaces_secret_when_provided():
    cfg = GatewayConfig()
    first = upsert_channel(
        cfg,
        entry_payload={
            "type": "slack",
            "name": "w",
            "token": "xoxb-old",
            "signing_secret": "ss-old",
        },
    )
    second = upsert_channel(
        first.config,
        entry_payload={"type": "slack", "name": "w", "token": "xoxb-new"},
    )
    raw = [e.model_dump(mode="python") for e in second.config.channels.channels]
    entry = next(e for e in raw if e["name"] == "w")
    assert entry["token"] == "xoxb-new"
