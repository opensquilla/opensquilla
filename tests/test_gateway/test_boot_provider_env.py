from __future__ import annotations

import tomllib
from types import SimpleNamespace

import pytest

from opensquilla.gateway.boot import _openai_compatible_catalog_sources
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

    assert runtime.provider_routing == {
        "deepseek/deepseek-v4-flash": "deepseek",
        "z-ai/glm-5.1": "z-ai",
        "anthropic/claude-opus-4.7": "anthropic",
        "moonshotai/kimi-k2.6": "moonshotai",
    }


def test_openrouter_runtime_provider_routing_overrides_default() -> None:
    cfg = GatewayConfig(
        llm={
            "provider": "openrouter",
            "provider_routing": {
                "z-ai/glm-5.1": "z-ai/fp8",
                "custom/model": "custom-provider",
            },
        }
    )

    runtime = resolve_llm_runtime_config(cfg)

    assert runtime.provider_routing["deepseek/deepseek-v4-flash"] == "deepseek"
    assert runtime.provider_routing["z-ai/glm-5.1"] == "z-ai/fp8"
    assert runtime.provider_routing["anthropic/claude-opus-4.7"] == "anthropic"
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
        GatewayConfig(squilla_router={"visual_mode": "all_models"})


def test_gateway_config_rejects_invalid_router_tier_tool_support() -> None:
    with pytest.raises(ValueError, match="tool_support must be one of"):
        GatewayConfig(
            squilla_router={
                "tiers": {
                    "c1": {
                        "provider": "openrouter",
                        "model": "z-ai/glm-5.1",
                        "toolSupport": "maybe",
                    }
                }
            }
        )


def test_openai_compatible_catalog_sources_include_router_tiers_and_dedupe(monkeypatch) -> None:
    monkeypatch.setenv("SELF_HOSTED_OPENAI_KEY", "tier-key")
    cfg = GatewayConfig(
        llm={
            "provider": "inception",
            "model": "inception/mercury-2",
            "api_key": "base-key",
            "base_url": "https://api.inceptionlabs.ai/v1",
        },
        squilla_router={
            "tiers": {
                "c1": {
                    "provider": "openai_compatible",
                    "model": "local-a",
                    "base_url": "http://localhost:8008/v1",
                    "api_key_env": "SELF_HOSTED_OPENAI_KEY",
                },
                "c2": {
                    "provider": "openai_compatible",
                    "model": "local-b",
                    "base_url": "http://localhost:8008",
                    "api_key_env": "SELF_HOSTED_OPENAI_KEY",
                },
                "c3": {
                    "provider": "openai_compatible",
                    "model": "local-c",
                    "base_url": "http://localhost:8009/v1",
                    "api_key": "other-key",
                },
            }
        },
    )

    sources = _openai_compatible_catalog_sources(
        cfg,
        base_provider="inception",
        base_url="https://api.inceptionlabs.ai/v1",
        api_key="base-key",
        proxy="",
    )

    assert [(s.provider_name, s.base_url, s.api_key) for s in sources] == [
        ("inception", "https://api.inceptionlabs.ai/v1", "base-key"),
        ("openai_compatible", "http://localhost:8008/v1", "tier-key"),
        ("openai_compatible", "http://localhost:8009/v1", "other-key"),
    ]


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


async def test_safe_config_patch_allows_tool_support_leaf_paths(tmp_path) -> None:
    cfg = GatewayConfig(config_path=str(tmp_path / "config.toml"))
    selector = _CapturingSelector()
    ctx = SimpleNamespace(config=cfg, provider_selector=selector)

    await _handle_config_patch_safe(
        {
            "patches": {
                "llm.tool_support": "off",
                "squilla_router.tiers.c1.tool_support": "on",
            }
        },
        ctx,
    )

    assert ctx.config.llm.tool_support == "off"
    assert ctx.config.squilla_router.tiers["c1"]["tool_support"] == "on"
    persisted = tomllib.loads((tmp_path / "config.toml").read_text())
    assert persisted["llm"]["tool_support"] == "off"
    assert persisted["squilla_router"]["tiers"]["c1"]["tool_support"] == "on"


async def test_safe_config_patch_allows_tool_schema_fit_leaf_paths(tmp_path) -> None:
    cfg = GatewayConfig(config_path=str(tmp_path / "config.toml"))
    selector = _CapturingSelector()
    ctx = SimpleNamespace(config=cfg, provider_selector=selector)

    await _handle_config_patch_safe(
        {
            "patches": {
                "llm.toolset": "web",
                "llm.max_tool_schema_chars": 12000,
                "squilla_router.tiers.c1.toolset": "web",
                "squilla_router.tiers.c1.max_tool_schema_chars": 12000,
            }
        },
        ctx,
    )

    assert ctx.config.llm.toolset == "web"
    assert ctx.config.llm.max_tool_schema_chars == 12000
    assert ctx.config.squilla_router.tiers["c1"]["toolset"] == "web"
    assert ctx.config.squilla_router.tiers["c1"]["max_tool_schema_chars"] == 12000
    persisted = tomllib.loads((tmp_path / "config.toml").read_text())
    assert persisted["llm"]["toolset"] == "web"
    assert persisted["llm"]["max_tool_schema_chars"] == 12000
    assert persisted["squilla_router"]["tiers"]["c1"]["toolset"] == "web"
    assert persisted["squilla_router"]["tiers"]["c1"]["max_tool_schema_chars"] == 12000


async def test_safe_config_patch_allows_router_visual_mode(tmp_path) -> None:
    cfg = GatewayConfig(config_path=str(tmp_path / "config.toml"))
    ctx = SimpleNamespace(config=cfg, provider_selector=_CapturingSelector())

    await _handle_config_patch_safe(
        {"patches": {"squilla_router.visual_mode": "legacy_grid"}},
        ctx,
    )

    assert ctx.config.squilla_router.visual_mode == "legacy_grid"
    persisted = tomllib.loads((tmp_path / "config.toml").read_text())
    assert persisted["squilla_router"]["visual_mode"] == "legacy_grid"


async def test_safe_config_patch_rejects_non_tool_support_tier_paths(tmp_path) -> None:
    cfg = GatewayConfig(config_path=str(tmp_path / "config.toml"))
    ctx = SimpleNamespace(config=cfg, provider_selector=_CapturingSelector())

    with pytest.raises(ValueError, match="Path is not safe"):
        await _handle_config_patch_safe(
            {"patches": {"squilla_router.tiers.c1.model": "custom/model"}},
            ctx,
        )
