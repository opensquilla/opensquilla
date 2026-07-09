"""Built-in default provider resolution in GatewayConfig.

The built-in default is tokenrhythm, but configs authored while openrouter
was the default must keep resolving to openrouter: an unset ``llm.provider``
falls back to openrouter when provider-coupled fields were explicitly set,
when ``squilla_router.tier_profile`` pins openrouter, or when the
environment carries only the openrouter credential. The resolution is
load-time only and must never be baked into config.toml by unrelated saves.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from opensquilla.gateway.config import (
    LEGACY_DEFAULT_LLM_BASE_URL,
    LEGACY_DEFAULT_LLM_MODEL,
    LEGACY_DEFAULT_LLM_PROVIDER,
    GatewayConfig,
    _default_tiers,
)

TOKENRHYTHM_BASE_URL = "https://tokenrhythm.studio/v1"


# ---------------------------------------------------------------------------
# Provider resolution
# ---------------------------------------------------------------------------


def test_keyless_default_resolves_tokenrhythm() -> None:
    cfg = GatewayConfig()
    assert cfg.llm.provider == "tokenrhythm"
    assert cfg.llm.model == "deepseek-v4-pro"
    assert cfg.llm.base_url == TOKENRHYTHM_BASE_URL


def test_openrouter_env_key_alone_keeps_legacy_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    cfg = GatewayConfig()
    assert cfg.llm.provider == LEGACY_DEFAULT_LLM_PROVIDER
    assert cfg.llm.model == LEGACY_DEFAULT_LLM_MODEL
    assert cfg.llm.base_url == LEGACY_DEFAULT_LLM_BASE_URL
    # The legacy default keeps the packaged openrouter ladder untouched.
    assert cfg.squilla_router.tiers == _default_tiers()


def test_tokenrhythm_env_key_resolves_tokenrhythm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TOKENRHYTHM_API_KEY", "sk_tr_test")
    cfg = GatewayConfig()
    assert cfg.llm.provider == "tokenrhythm"


def test_both_env_keys_prefer_tokenrhythm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setenv("TOKENRHYTHM_API_KEY", "sk_tr_test")
    cfg = GatewayConfig()
    assert cfg.llm.provider == "tokenrhythm"


@pytest.mark.parametrize(
    "llm_overrides",
    [
        {"api_key": "sk-or-raw"},
        {"api_key_env": "MY_OPENROUTER_KEY"},
        {"model": "anthropic/claude-sonnet-5"},
        {"base_url": "https://openrouter.ai/api/v1"},
    ],
)
def test_provider_coupled_fields_without_provider_mean_openrouter(
    llm_overrides: dict,
) -> None:
    # These fields were authored against the pre-tokenrhythm default and must
    # keep binding to openrouter when the provider was never named.
    cfg = GatewayConfig(llm=llm_overrides)
    assert cfg.llm.provider == LEGACY_DEFAULT_LLM_PROVIDER
    if "model" not in llm_overrides:
        assert cfg.llm.model == LEGACY_DEFAULT_LLM_MODEL
    else:
        assert cfg.llm.model == llm_overrides["model"]
    if "base_url" not in llm_overrides:
        assert cfg.llm.base_url == LEGACY_DEFAULT_LLM_BASE_URL


def test_openrouter_tier_profile_without_provider_means_openrouter() -> None:
    # tier_profile must match the provider, so a persisted openrouter profile
    # from the pre-tokenrhythm era must keep loading (not raise).
    cfg = GatewayConfig(squilla_router={"tier_profile": "openrouter"})
    assert cfg.llm.provider == LEGACY_DEFAULT_LLM_PROVIDER
    assert cfg.squilla_router.tier_profile == "openrouter"


def test_explicit_openrouter_backfills_legacy_model_and_base_url() -> None:
    # provider = "openrouter" written while model/base_url fell back to the
    # old field defaults must keep meaning those defaults.
    cfg = GatewayConfig(llm={"provider": "openrouter", "api_key": "x"})
    assert cfg.llm.model == LEGACY_DEFAULT_LLM_MODEL
    assert cfg.llm.base_url == LEGACY_DEFAULT_LLM_BASE_URL


def test_explicit_openrouter_keeps_explicit_model_and_base_url() -> None:
    cfg = GatewayConfig(
        llm={
            "provider": "openrouter",
            "model": "z-ai/glm-5.2",
            "base_url": "https://proxy.example/v1",
        }
    )
    assert cfg.llm.model == "z-ai/glm-5.2"
    assert cfg.llm.base_url == "https://proxy.example/v1"


def test_explicit_other_provider_is_untouched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    cfg = GatewayConfig(llm={"provider": "deepseek", "model": "deepseek-chat"})
    assert cfg.llm.provider == "deepseek"
    assert cfg.llm.model == "deepseek-chat"


# ---------------------------------------------------------------------------
# Default router ladder under the tokenrhythm default
# ---------------------------------------------------------------------------


def test_tokenrhythm_default_binds_router_tiers_to_tokenrhythm() -> None:
    cfg = GatewayConfig()
    tiers = cfg.squilla_router.tiers
    for name in ("c0", "c1", "c2", "c3"):
        assert tiers[name]["provider"] == "tokenrhythm"
        assert tiers[name]["model"] == "deepseek-v4-pro"
    # Synthesized presets carry no curated image tier.
    assert "image_model" not in tiers
    assert cfg.squilla_router.tier_profile is None


def test_tokenrhythm_tiers_follow_the_effective_model() -> None:
    cfg = GatewayConfig(llm={"provider": "tokenrhythm", "model": "glm-5.1"})
    assert cfg.squilla_router.tiers["c1"]["model"] == "glm-5.1"


def test_tokenrhythm_custom_tiers_are_preserved() -> None:
    custom = {"c1": {"provider": "tokenrhythm", "model": "kimi-k2.6"}}
    cfg = GatewayConfig(llm={"provider": "tokenrhythm"}, squilla_router={"tiers": custom})
    assert cfg.squilla_router.tiers["c1"]["model"] == "kimi-k2.6"


def test_tokenrhythm_disabled_router_keeps_default_tiers() -> None:
    cfg = GatewayConfig(squilla_router={"enabled": False})
    assert cfg.squilla_router.tiers == _default_tiers()


def test_legacy_nine_auto_profile_still_applies() -> None:
    # The direct-provider auto tier_profile default must survive the new
    # validators running ahead of it.
    cfg = GatewayConfig(llm={"provider": "deepseek", "model": "deepseek-chat"})
    assert cfg.squilla_router.tier_profile == "deepseek"


# ---------------------------------------------------------------------------
# Resolution must not be baked into config.toml
# ---------------------------------------------------------------------------


def test_resolved_legacy_provider_is_not_persisted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import tomllib

    from opensquilla.onboarding.config_store import load_config, persist_config

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    target = tmp_path / "config.toml"
    target.write_text('log_level = "INFO"\n', encoding="utf-8")

    cfg = load_config(target)
    assert cfg.llm.provider == LEGACY_DEFAULT_LLM_PROVIDER

    cfg.log_level = "DEBUG"
    persist_config(cfg, path=target, backup=False)

    data = tomllib.loads(target.read_text(encoding="utf-8"))
    assert data["log_level"] == "DEBUG"
    assert "llm" not in data
    assert "squilla_router" not in data


def test_resolved_tokenrhythm_tiers_are_not_persisted(tmp_path: Path) -> None:
    import tomllib

    from opensquilla.onboarding.config_store import load_config, persist_config

    target = tmp_path / "config.toml"
    target.write_text('log_level = "INFO"\n', encoding="utf-8")

    cfg = load_config(target)
    assert cfg.squilla_router.tiers["c1"]["provider"] == "tokenrhythm"

    cfg.log_level = "DEBUG"
    persist_config(cfg, path=target, backup=False)

    data = tomllib.loads(target.read_text(encoding="utf-8"))
    assert "squilla_router" not in data
    assert "llm" not in data
