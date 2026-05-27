"""Per-section verifier behaviour and the ``needs_onboarding`` reduction."""

from __future__ import annotations

import pytest

from opensquilla.gateway.config import (
    GatewayConfig,
    LlmProviderConfig,
    MemoryEmbeddingConfig,
    SlackChannelEntry,
)
from opensquilla.onboarding.section_status import (
    SectionStatus,
    channels_section_status,
    image_generation_section_status,
    llm_section_status,
    memory_embedding_section_status,
    needs_onboarding,
    router_section_status,
    search_section_status,
)


@pytest.fixture()
def cfg() -> GatewayConfig:
    return GatewayConfig()


# ── llm ─────────────────────────────────────────────────────────────────────

def test_llm_missing_when_provider_unset(cfg):
    cfg.llm = LlmProviderConfig(provider="", model="", api_key="")
    assert llm_section_status(cfg) is SectionStatus.MISSING


def test_llm_ok_with_explicit_api_key(cfg):
    cfg.llm = LlmProviderConfig(
        provider="openrouter",
        model="m",
        api_key="sk-x",
        base_url="https://openrouter.ai/api/v1",
    )
    assert llm_section_status(cfg) is SectionStatus.OK


def test_llm_ok_with_env_key_present(cfg, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "from-env")
    cfg.llm = LlmProviderConfig(
        provider="openrouter",
        model="m",
        api_key="",
        api_key_env="OPENROUTER_API_KEY",
        base_url="https://openrouter.ai/api/v1",
    )
    assert llm_section_status(cfg) is SectionStatus.OK


def test_llm_degraded_when_env_key_missing(cfg, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    cfg.llm = LlmProviderConfig(
        provider="openrouter",
        model="m",
        api_key="",
        api_key_env="OPENROUTER_API_KEY",
        base_url="https://openrouter.ai/api/v1",
    )
    assert llm_section_status(cfg) is SectionStatus.DEGRADED


def test_llm_unknown_for_unsupported_provider(cfg):
    cfg.llm = LlmProviderConfig(provider="no-such-provider", model="m")
    assert llm_section_status(cfg) is SectionStatus.UNKNOWN


# ── router ──────────────────────────────────────────────────────────────────

def test_router_disabled_is_optional(cfg):
    cfg.squilla_router.enabled = False
    assert router_section_status(cfg) is SectionStatus.OPTIONAL


def test_router_enabled_is_ok(cfg):
    cfg.squilla_router.enabled = True
    assert router_section_status(cfg) is SectionStatus.OK


# ── search ──────────────────────────────────────────────────────────────────

def test_search_unset_is_optional(cfg, monkeypatch):
    cfg.search_provider = ""
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    assert search_section_status(cfg) is SectionStatus.OPTIONAL


def test_search_duckduckgo_default_is_ok(cfg):
    cfg.search_provider = "duckduckgo"
    cfg.search_api_key = ""
    cfg.search_api_key_env = ""
    assert search_section_status(cfg) is SectionStatus.OK


def test_search_brave_with_explicit_key_is_ok(cfg):
    cfg.search_provider = "brave"
    cfg.search_api_key = "secret"
    assert search_section_status(cfg) is SectionStatus.OK


def test_search_brave_without_credentials_is_missing(cfg, monkeypatch):
    cfg.search_provider = "brave"
    cfg.search_api_key = ""
    cfg.search_api_key_env = ""
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    assert search_section_status(cfg) is SectionStatus.MISSING


def test_search_brave_with_env_key_missing_is_degraded(cfg, monkeypatch):
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    cfg.search_provider = "brave"
    cfg.search_api_key = ""
    cfg.search_api_key_env = "BRAVE_API_KEY"
    assert search_section_status(cfg) is SectionStatus.DEGRADED


def test_search_unknown_provider_is_unknown(cfg):
    cfg.search_provider = "no-such-search"
    assert search_section_status(cfg) is SectionStatus.UNKNOWN


# ── channels ────────────────────────────────────────────────────────────────

def test_channels_empty_is_optional(cfg):
    cfg.channels.channels.clear()
    assert channels_section_status(cfg) is SectionStatus.OPTIONAL


def test_channels_all_disabled_is_optional(cfg):
    cfg.channels.channels.clear()
    cfg.channels.channels.append(
        SlackChannelEntry(name="work", enabled=False, token="x")
    )
    assert channels_section_status(cfg) is SectionStatus.OPTIONAL


def test_channels_any_enabled_is_ok(cfg):
    cfg.channels.channels.clear()
    cfg.channels.channels.append(
        SlackChannelEntry(name="work", enabled=True, token="x")
    )
    assert channels_section_status(cfg) is SectionStatus.OK


# ── image generation ────────────────────────────────────────────────────────

def test_image_generation_disabled_is_optional(cfg):
    cfg.image_generation.enabled = False
    assert image_generation_section_status(cfg) is SectionStatus.OPTIONAL


def test_image_generation_enabled_without_credentials_is_missing(cfg, monkeypatch):
    cfg.image_generation.enabled = True
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    # No provider credentials anywhere, LLM provider is not the image provider.
    cfg.llm = LlmProviderConfig(provider="openrouter", model="m", api_key="")
    assert image_generation_section_status(cfg) is SectionStatus.MISSING


def test_image_generation_unknown_provider_reference_is_unknown(cfg, monkeypatch):
    cfg.image_generation.enabled = True
    cfg.image_generation.primary = "no-such-provider/no-such-model"
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert image_generation_section_status(cfg) is SectionStatus.UNKNOWN


def test_image_generation_env_key_reference_missing_is_degraded(cfg, monkeypatch):
    cfg.image_generation.enabled = True
    cfg.image_generation.primary = "openai/gpt-image-1"
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("CUSTOM_IMAGE_KEY", raising=False)
    cfg.llm = LlmProviderConfig(provider="openrouter", model="m", api_key="")
    # Wire an explicit env reference to a variable that is not set.
    openai_provider = cfg.image_generation.providers.openai
    openai_provider.api_key = ""
    openai_provider.api_key_env = "CUSTOM_IMAGE_KEY"
    assert image_generation_section_status(cfg) is SectionStatus.DEGRADED


def test_image_generation_missing_custom_env_is_not_masked_by_default_env(
    cfg,
    monkeypatch,
):
    cfg.image_generation.enabled = True
    cfg.image_generation.primary = "openai/gpt-image-1"
    cfg.llm = LlmProviderConfig(provider="openrouter", model="m", api_key="")
    openai_provider = cfg.image_generation.providers.openai
    openai_provider.api_key = ""
    openai_provider.api_key_env = "CUSTOM_IMAGE_KEY"
    monkeypatch.delenv("CUSTOM_IMAGE_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "default-env-key")

    assert image_generation_section_status(cfg) is SectionStatus.DEGRADED


def test_image_generation_custom_default_primary_is_not_masked_by_other_provider(
    cfg,
    monkeypatch,
):
    cfg.image_generation.enabled = True
    cfg.image_generation.primary = "openai/gpt-image-1"
    cfg.llm = LlmProviderConfig(provider="openrouter", model="m", api_key="sk-or")
    openai_provider = cfg.image_generation.providers.openai
    openai_provider.api_key = ""
    openai_provider.api_key_env = "CUSTOM_IMAGE_KEY"
    monkeypatch.delenv("CUSTOM_IMAGE_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    assert image_generation_section_status(cfg) is SectionStatus.DEGRADED


# ── memory embedding ────────────────────────────────────────────────────────

def test_memory_embedding_auto_is_ok(cfg):
    cfg.memory.embedding = MemoryEmbeddingConfig(provider="auto")
    assert memory_embedding_section_status(cfg) is SectionStatus.OK


def test_memory_embedding_none_is_optional(cfg):
    cfg.memory.embedding = MemoryEmbeddingConfig(provider="none")
    assert memory_embedding_section_status(cfg) is SectionStatus.OPTIONAL


def test_memory_embedding_remote_without_key_is_missing(cfg):
    cfg.memory.embedding = MemoryEmbeddingConfig(provider="openai")
    assert memory_embedding_section_status(cfg) is SectionStatus.MISSING


def test_memory_embedding_remote_with_missing_env_key_is_degraded(cfg, monkeypatch):
    monkeypatch.delenv("OPENAI_EMBEDDINGS_API_KEY", raising=False)
    cfg.memory.embedding = MemoryEmbeddingConfig(
        provider="openai",
        remote={"api_key_env": "OPENAI_EMBEDDINGS_API_KEY"},
    )

    assert memory_embedding_section_status(cfg) is SectionStatus.DEGRADED


def test_memory_embedding_remote_with_env_key_is_ok(cfg, monkeypatch):
    monkeypatch.setenv("OPENAI_EMBEDDINGS_API_KEY", "mem-env-key")
    cfg.memory.embedding = MemoryEmbeddingConfig(
        provider="openai",
        remote={"api_key_env": "OPENAI_EMBEDDINGS_API_KEY"},
    )

    assert memory_embedding_section_status(cfg) is SectionStatus.OK


def test_memory_embedding_remote_with_key_is_ok(cfg):
    cfg.memory.embedding = MemoryEmbeddingConfig(
        provider="openai",
        remote={"api_key": "sk-embedding"},
    )
    assert memory_embedding_section_status(cfg) is SectionStatus.OK


# ── needs_onboarding reduction ───────────────────────────────────────────────

def test_needs_onboarding_false_when_all_ok_or_optional():
    sections = {
        "llm": SectionStatus.OK,
        "router": SectionStatus.OPTIONAL,
        "search": SectionStatus.OK,
        "channels": SectionStatus.OPTIONAL,
        "image_generation": SectionStatus.OPTIONAL,
        "memory_embedding": SectionStatus.OK,
    }
    assert needs_onboarding(sections) is False


def test_needs_onboarding_false_when_optional_section_missing():
    sections = {
        "llm": SectionStatus.OK,
        "router": SectionStatus.OPTIONAL,
        "search": SectionStatus.MISSING,
        "channels": SectionStatus.OPTIONAL,
        "image_generation": SectionStatus.OPTIONAL,
        "memory_embedding": SectionStatus.OK,
    }
    assert needs_onboarding(sections) is False


def test_needs_onboarding_true_when_required_section_degraded():
    sections = {
        "llm": SectionStatus.DEGRADED,
        "router": SectionStatus.OK,
        "search": SectionStatus.OK,
        "channels": SectionStatus.OPTIONAL,
        "image_generation": SectionStatus.OPTIONAL,
        "memory_embedding": SectionStatus.OK,
    }
    assert needs_onboarding(sections) is True


def test_needs_onboarding_false_when_optional_section_unknown():
    sections = {
        "llm": SectionStatus.OK,
        "router": SectionStatus.UNKNOWN,
        "search": SectionStatus.OK,
        "channels": SectionStatus.OPTIONAL,
        "image_generation": SectionStatus.OPTIONAL,
        "memory_embedding": SectionStatus.OK,
    }
    assert needs_onboarding(sections) is False
