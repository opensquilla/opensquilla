from __future__ import annotations

import tomllib
from types import SimpleNamespace

import pytest

from opensquilla.gateway.config import GatewayConfig
from opensquilla.gateway.llm_runtime import resolve_llm_runtime_config
from opensquilla.gateway.rpc_config import (
    _handle_config_patch,
    _handle_config_patch_safe,
    _sync_provider_selector,
)


class _CapturingSelector:
    def __init__(self) -> None:
        self.synced = None

    def sync_primary(self, cfg) -> None:
        self.synced = cfg


def test_boot_resolves_direct_provider_env_key_and_base_url(
    monkeypatch,
) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_BASE_URL", raising=False)
    monkeypatch.setenv("VOLCENGINE_API_KEY", "volc-key")
    monkeypatch.setenv("VOLCENGINE_BASE_URL", "https://ark.example/api/v3")

    cfg = GatewayConfig(llm={"provider": "volcengine", "api_key": "", "base_url": ""})

    runtime = resolve_llm_runtime_config(cfg)

    assert runtime.api_key == "volc-key"
    assert runtime.base_url == "https://ark.example/api/v3"
    assert runtime.api_key_from_env is True
    assert runtime.base_url_from_env is True
    assert cfg.llm.api_key == "volc-key"
    assert cfg.llm.base_url == "https://ark.example/api/v3"


def test_boot_uses_explicit_key_before_standard_env(monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://openrouter.example/api/v1")
    monkeypatch.setenv("VOLCENGINE_API_KEY", "volc-key")
    cfg = GatewayConfig(
        llm={
            "provider": "openrouter",
            "api_key": "config-key",
            "base_url": "https://config.example/api/v1",
        }
    )

    runtime = resolve_llm_runtime_config(cfg)

    assert runtime.api_key == "config-key"
    assert runtime.api_key_from_env is False
    assert runtime.base_url == "https://openrouter.example/api/v1"


def test_openrouter_runtime_uses_default_provider_routing() -> None:
    cfg = GatewayConfig(llm={"provider": "openrouter"})

    runtime = resolve_llm_runtime_config(cfg)

    assert runtime.provider_routing["deepseek/deepseek-v4-flash"] == "deepseek"
    assert runtime.provider_routing["z-ai/glm-5.1"] == "z-ai"
    assert runtime.provider_routing["z-ai/glm-5.2"] == "z-ai"
    assert runtime.provider_routing["anthropic/claude-opus-4.8"] == "anthropic"
    assert runtime.provider_routing["moonshotai/kimi-k2.6"] == "moonshotai"
    assert runtime.provider_routing["openai/gpt-5.5"] == "openai"


def test_openrouter_runtime_provider_routing_overrides_default() -> None:
    cfg = GatewayConfig(
        llm={
            "provider": "openrouter",
            "provider_routing": {
                "z-ai/glm-5.2": "z-ai/special",
                "custom/model": "custom-provider",
            },
        }
    )

    runtime = resolve_llm_runtime_config(cfg)

    assert runtime.provider_routing["deepseek/deepseek-v4-flash"] == "deepseek"
    assert runtime.provider_routing["z-ai/glm-5.2"] == "z-ai/special"
    assert runtime.provider_routing["anthropic/claude-opus-4.8"] == "anthropic"
    assert runtime.provider_routing["moonshotai/kimi-k2.6"] == "moonshotai"
    assert runtime.provider_routing["custom/model"] == "custom-provider"


def test_direct_provider_runtime_does_not_inherit_openrouter_provider_routing() -> None:
    cfg = GatewayConfig(llm={"provider": "deepseek", "api_key": "", "base_url": ""})

    runtime = resolve_llm_runtime_config(cfg)

    assert runtime.provider_routing == {}


def test_squilla_router_visual_mode_defaults_to_real_candidates() -> None:
    cfg = GatewayConfig()

    assert cfg.squilla_router.visual_mode == "real_candidates"
    assert cfg.to_public_dict()["squilla_router"]["visual_mode"] == "real_candidates"


def test_squilla_router_visual_mode_accepts_legacy_grid_and_model_space_alias() -> None:
    legacy_cfg = GatewayConfig(squilla_router={"visual_mode": "legacy_grid"})
    alias_cfg = GatewayConfig(squilla_router={"visual_mode": "model_space"})
    dashed_alias_cfg = GatewayConfig(squilla_router={"visual_mode": "model-space"})

    assert legacy_cfg.squilla_router.visual_mode == "legacy_grid"
    assert alias_cfg.squilla_router.visual_mode == "legacy_grid"
    assert dashed_alias_cfg.squilla_router.visual_mode == "legacy_grid"


def test_squilla_router_visual_mode_rejects_unknown_value() -> None:
    with pytest.raises(ValueError, match="visual_mode must be one of"):
        GatewayConfig(squilla_router={"visual_mode": "local_storage"})


def test_runtime_config_sync_resolves_selected_provider_env(monkeypatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://deepseek.example")
    cfg = GatewayConfig(llm={"provider": "deepseek", "api_key": "", "base_url": ""})
    selector = _CapturingSelector()
    ctx = type("Ctx", (), {"provider_selector": selector})()

    _sync_provider_selector(ctx, cfg)

    assert selector.synced.provider == "deepseek"
    assert selector.synced.api_key == "deepseek-key"
    assert selector.synced.base_url == "https://deepseek.example"


async def test_config_patch_runtime_env_key_is_not_persisted(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://deepseek.example")
    cfg = GatewayConfig(
        config_path=str(tmp_path / "config.toml"),
        llm={"provider": "openai", "api_key": "", "base_url": ""},
    )
    selector = _CapturingSelector()
    ctx = SimpleNamespace(config=cfg, provider_selector=selector)

    await _handle_config_patch({"patch": {"llm": {"provider": "deepseek"}}}, ctx)

    assert ctx.config.squilla_router.tier_profile == "deepseek"
    assert ctx.config.llm.api_key == "deepseek-key"
    assert selector.synced.api_key == "deepseek-key"
    assert "api_key" not in ctx.config.to_toml_dict()["llm"]
    persisted = tomllib.loads((tmp_path / "config.toml").read_text())
    assert persisted["squilla_router"]["tier_profile"] == "deepseek"
    assert "api_key" not in persisted["llm"]


async def test_config_patch_safe_accepts_router_visual_mode(tmp_path) -> None:
    cfg = GatewayConfig(config_path=str(tmp_path / "config.toml"))
    ctx = SimpleNamespace(config=cfg)

    res = await _handle_config_patch_safe(
        {"patches": {"squilla_router.visual_mode": "legacy_grid"}},
        ctx,
    )

    assert res["patched"] == ["squilla_router.visual_mode"]
    assert res["restartRequired"] is False
    assert ctx.config.squilla_router.visual_mode == "legacy_grid"
    persisted = tomllib.loads((tmp_path / "config.toml").read_text())
    assert persisted["squilla_router"]["visual_mode"] == "legacy_grid"
