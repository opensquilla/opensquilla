"""RPC tests for onboarding handlers."""

from __future__ import annotations

import platform
import tomllib

import pytest

import opensquilla.gateway.rpc_onboarding  # noqa: F401  ensures registration
from opensquilla.gateway.auth import Principal
from opensquilla.gateway.rpc import RpcContext, get_dispatcher


def _env_hint(env_key: str) -> str:
    if platform.system().lower().startswith("win"):
        return f'PowerShell: $env:{env_key} = "<your-key>"'
    return f'export {env_key}="<your-key>"'


def _admin_ctx() -> RpcContext:
    return RpcContext(
        conn_id="t",
        principal=Principal(
            role="operator",
            scopes=frozenset({"operator.admin"}),
            is_owner=True,
            authenticated=True,
        ),
    )


def _read_ctx() -> RpcContext:
    return RpcContext(
        conn_id="t",
        principal=Principal(
            role="operator",
            scopes=frozenset({"operator.read"}),
            is_owner=False,
            authenticated=True,
        ),
    )


@pytest.mark.asyncio
async def test_onboarding_status_works_with_read_scope(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(tmp_path / "c.toml"))
    res = await get_dispatcher().dispatch("r1", "onboarding.status", {}, _read_ctx())
    assert res.error is None, res.error
    assert "needsOnboarding" in res.payload
    assert "configPath" in res.payload
    assert "sections" in res.payload
    assert "sectionDetails" in res.payload
    assert "memory_embedding" in res.payload["sections"]


@pytest.mark.asyncio
async def test_onboarding_catalog_returns_providers_and_channels(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(tmp_path / "c.toml"))
    res = await get_dispatcher().dispatch("r1", "onboarding.catalog", {}, _read_ctx())
    assert res.error is None, res.error
    payload = res.payload
    assert "providers" in payload
    assert "channels" in payload
    assert "searchProviders" in payload
    assert "routerProfiles" in payload
    assert "imageGenerationProviders" in payload
    assert "memoryEmbeddingProviders" in payload
    types = {c["type"] for c in payload["channels"]}
    assert {"slack", "telegram", "matrix", "discord"} <= types
    search_provider_ids = {p["providerId"] for p in payload["searchProviders"]}
    assert {"brave", "duckduckgo"} <= search_provider_ids
    image_provider_ids = {p["providerId"] for p in payload["imageGenerationProviders"]}
    assert {"openai", "openrouter"} <= image_provider_ids
    memory_provider_ids = {p["providerId"] for p in payload["memoryEmbeddingProviders"]}
    assert {
        "auto",
        "local",
        "openai",
        "openai-compatible",
        "ollama",
        "none",
    } <= memory_provider_ids
    assert all("whatYouNeed" in p for p in payload["memoryEmbeddingProviders"])
    router_profile_ids = {p["profileId"] for p in payload["routerProfiles"]["profiles"]}
    assert {"openrouter", "deepseek", "openai"} <= router_profile_ids


@pytest.mark.asyncio
async def test_provider_configure_redacts_api_key(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(tmp_path / "c.toml"))
    res = await get_dispatcher().dispatch(
        "r1",
        "onboarding.provider.configure",
        {"providerId": "openrouter", "model": "x", "apiKey": "sk-test"},
        _admin_ctx(),
    )
    assert res.error is None, res.error
    assert res.payload["changed"] is True
    assert res.payload["entry"]["api_key"] == "***"
    assert res.payload["restartRequired"] is False


@pytest.mark.asyncio
async def test_provider_configure_can_omit_model_for_router_profile(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(tmp_path / "c.toml"))
    res = await get_dispatcher().dispatch(
        "r1",
        "onboarding.provider.configure",
        {"providerId": "deepseek", "apiKeyEnv": "DEEPSEEK_API_KEY"},
        _admin_ctx(),
    )
    assert res.error is None, res.error
    assert res.payload["entry"]["model"] == "deepseek-v4-flash"
    data = tomllib.loads((tmp_path / "c.toml").read_text())
    assert data["llm"]["model"] == "deepseek-v4-flash"
    assert data["squilla_router"]["tier_profile"] == "deepseek"


@pytest.mark.asyncio
async def test_router_configure_recommended_profile(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(tmp_path / "c.toml"))
    from opensquilla.gateway.config import GatewayConfig

    ctx = _admin_ctx()
    ctx.config = GatewayConfig(llm={"provider": "deepseek", "model": "deepseek-chat"})
    ctx.config.config_path = str(tmp_path / "c.toml")

    res = await get_dispatcher().dispatch(
        "r1",
        "onboarding.router.configure",
        {"mode": "recommended"},
        ctx,
    )

    assert res.error is None, res.error
    assert ctx.config.squilla_router.enabled is True
    assert ctx.config.squilla_router.tier_profile == "deepseek"
    persisted = tomllib.loads((tmp_path / "c.toml").read_text())
    assert persisted["squilla_router"]["tier_profile"] == "deepseek"
    assert "tiers" not in persisted["squilla_router"]


@pytest.mark.asyncio
async def test_router_configure_accepts_tier_overrides_and_syncs_llm_model(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(tmp_path / "c.toml"))
    from opensquilla.gateway.config import GatewayConfig

    ctx = _admin_ctx()
    ctx.config = GatewayConfig(llm={"provider": "openai", "model": "gpt-5.4-mini"})
    ctx.config.config_path = str(tmp_path / "c.toml")

    res = await get_dispatcher().dispatch(
        "r1",
        "onboarding.router.configure",
        {
            "mode": "recommended",
            "defaultTier": "t2",
            "tiers": {
                "t2": {"provider": "openai", "model": "gpt-5.5-custom"},
                "image_model": {
                    "provider": "openai",
                    "model": "gpt-5.4-mini",
                    "supportsImage": True,
                },
            },
        },
        ctx,
    )

    assert res.error is None, res.error
    assert ctx.config.llm.model == "gpt-5.5-custom"
    assert ctx.config.squilla_router.default_tier == "t2"
    persisted = tomllib.loads((tmp_path / "c.toml").read_text())
    assert persisted["llm"]["model"] == "gpt-5.5-custom"
    assert persisted["squilla_router"]["tiers"]["t2"]["model"] == "gpt-5.5-custom"
    assert persisted["squilla_router"]["tiers"]["image_model"]["supports_image"] is True


@pytest.mark.asyncio
async def test_router_configure_rejects_image_model_as_default_tier(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(tmp_path / "c.toml"))
    from opensquilla.gateway.config import GatewayConfig

    ctx = _admin_ctx()
    ctx.config = GatewayConfig(llm={"provider": "openrouter", "model": "m"})
    ctx.config.config_path = str(tmp_path / "c.toml")

    res = await get_dispatcher().dispatch(
        "r1",
        "onboarding.router.configure",
        {"mode": "recommended", "defaultTier": "image_model"},
        ctx,
    )

    assert res.error is not None
    assert "defaultTier must reference a text tier" in res.error.message


@pytest.mark.asyncio
async def test_provider_configure_recomputes_existing_router_profile(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(tmp_path / "c.toml"))
    from opensquilla.gateway.config import GatewayConfig

    ctx = _admin_ctx()
    ctx.config = GatewayConfig(
        llm={"provider": "deepseek", "model": "deepseek-chat"},
        squilla_router={"tier_profile": "deepseek"},
    )
    ctx.config.config_path = str(tmp_path / "c.toml")

    res = await get_dispatcher().dispatch(
        "r1",
        "onboarding.provider.configure",
        {
            "providerId": "openai",
            "model": "gpt-5.4-mini",
            "apiKeyEnv": "OPENAI_API_KEY",
        },
        ctx,
    )

    assert res.error is None, res.error
    assert ctx.config.llm.provider == "openai"
    assert ctx.config.squilla_router.tier_profile == "openai"
    persisted = tomllib.loads((tmp_path / "c.toml").read_text())
    assert persisted["squilla_router"]["tier_profile"] == "openai"
    assert "tiers" not in persisted["squilla_router"]


@pytest.mark.asyncio
async def test_provider_configure_recomputes_openrouter_mix_router(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(tmp_path / "c.toml"))
    from opensquilla.gateway.config import GatewayConfig

    ctx = _admin_ctx()
    ctx.config = GatewayConfig(llm={"provider": "openrouter", "model": "deepseek/x"})
    ctx.config.config_path = str(tmp_path / "c.toml")

    res = await get_dispatcher().dispatch(
        "r1",
        "onboarding.provider.configure",
        {
            "providerId": "deepseek",
            "model": "deepseek-chat",
            "apiKeyEnv": "DEEPSEEK_API_KEY",
        },
        ctx,
    )

    assert res.error is None, res.error
    assert ctx.config.llm.provider == "deepseek"
    assert ctx.config.squilla_router.enabled is True
    assert ctx.config.squilla_router.tier_profile == "deepseek"
    persisted = tomllib.loads((tmp_path / "c.toml").read_text())
    assert persisted["squilla_router"]["tier_profile"] == "deepseek"
    assert "tiers" not in persisted["squilla_router"]


@pytest.mark.asyncio
async def test_router_catalog_rpc(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(tmp_path / "c.toml"))

    res = await get_dispatcher().dispatch(
        "r1",
        "onboarding.router.catalog",
        {},
        _read_ctx(),
    )

    assert res.error is None, res.error
    profile_ids = {p["profileId"] for p in res.payload["profiles"]}
    assert {"openrouter", "deepseek"} <= profile_ids


@pytest.mark.asyncio
async def test_channel_upsert_redacts_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(tmp_path / "c.toml"))
    res = await get_dispatcher().dispatch(
        "r1",
        "onboarding.channel.upsert",
        {"entry": {"type": "slack", "name": "w", "token": "supersecret"}},
        _admin_ctx(),
    )
    assert res.error is None, res.error
    assert res.payload["changed"] is True
    assert res.payload["restartRequired"] is True
    assert res.payload["entry"]["token"] == "***"


@pytest.mark.asyncio
async def test_channel_probe_validates_and_redacts_without_persisting(tmp_path, monkeypatch):
    target = tmp_path / "c.toml"
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(target))
    res = await get_dispatcher().dispatch(
        "r1",
        "onboarding.channel.probe",
        {
            "entry": {
                "type": "telegram",
                "name": "tg",
                "token": "123:secret",
                "transport_name": "polling",
            }
        },
        _admin_ctx(),
    )
    assert res.error is None, res.error
    assert res.payload["status"] in {"ready", "action_needed"}
    assert res.payload["entry"]["token"] == "***"
    assert "123:secret" not in str(res.payload)
    assert not target.exists()


@pytest.mark.asyncio
async def test_search_configure_redacts_api_key(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(tmp_path / "c.toml"))
    res = await get_dispatcher().dispatch(
        "r1",
        "onboarding.search.configure",
        {"providerId": "brave", "apiKey": "brave-secret", "maxResults": 3},
        _admin_ctx(),
    )
    assert res.error is None, res.error
    assert res.payload["changed"] is True
    assert res.payload["entry"]["api_key"] == "***"


@pytest.mark.asyncio
async def test_search_configure_accepts_webui_string_max_results(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(tmp_path / "c.toml"))

    res = await get_dispatcher().dispatch(
        "r1",
        "onboarding.search.configure",
        {"providerId": "duckduckgo", "maxResults": "5"},
        _admin_ctx(),
    )

    assert res.error is None, res.error
    assert res.payload["entry"]["max_results"] == 5


@pytest.mark.asyncio
async def test_image_generation_configure_redacts_api_key(tmp_path, monkeypatch):
    target = tmp_path / "c.toml"
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(target))
    res = await get_dispatcher().dispatch(
        "r1",
        "onboarding.imageGeneration.configure",
        {
            "providerId": "openrouter",
            "primary": "openrouter/google/gemini-3.1-flash-image-preview",
            "apiKey": "sk-or",
        },
        _admin_ctx(),
    )
    assert res.error is None, res.error
    assert res.payload["changed"] is True
    assert res.payload["restartRequired"] is False
    assert res.payload["entry"]["api_key"] == "***"

    data = tomllib.loads(target.read_text())
    assert data["image_generation"]["enabled"] is True
    assert (
        data["image_generation"]["primary"]
        == "openrouter/google/gemini-3.1-flash-image-preview"
    )
    assert data["image_generation"]["providers"]["openrouter"]["api_key"] == "sk-or"


@pytest.mark.asyncio
async def test_image_generation_configure_can_use_custom_env_reference(
    tmp_path,
    monkeypatch,
):
    target = tmp_path / "c.toml"
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(target))
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("OPENSQUILLA_TEST_IMAGE_KEY", "sk-image-env")

    res = await get_dispatcher().dispatch(
        "r1",
        "onboarding.imageGeneration.configure",
        {
            "providerId": "openrouter",
            "primary": "openrouter/google/gemini-3.1-flash-image-preview",
            "apiKeyEnv": "OPENSQUILLA_TEST_IMAGE_KEY",
        },
        _admin_ctx(),
    )

    assert res.error is None, res.error
    assert res.payload["entry"]["api_key_source"] == "env"
    assert res.payload["entry"]["api_key_env"] == "OPENSQUILLA_TEST_IMAGE_KEY"
    data = tomllib.loads(target.read_text())
    provider = data["image_generation"]["providers"]["openrouter"]
    assert provider["api_key"] == ""
    assert provider["api_key_env"] == "OPENSQUILLA_TEST_IMAGE_KEY"


@pytest.mark.asyncio
async def test_image_generation_configure_can_save_missing_custom_env_reference(
    tmp_path,
    monkeypatch,
):
    target = tmp_path / "c.toml"
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(target))
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENSQUILLA_TEST_IMAGE_KEY", raising=False)

    res = await get_dispatcher().dispatch(
        "r1",
        "onboarding.imageGeneration.configure",
        {
            "providerId": "openrouter",
            "primary": "openrouter/google/gemini-3.1-flash-image-preview",
            "apiKeyEnv": "OPENSQUILLA_TEST_IMAGE_KEY",
        },
        _admin_ctx(),
    )

    assert res.error is None, res.error
    assert res.payload["entry"]["api_key_source"] == "missing_env"
    assert res.payload["entry"]["api_key_env"] == "OPENSQUILLA_TEST_IMAGE_KEY"
    data = tomllib.loads(target.read_text())
    provider = data["image_generation"]["providers"]["openrouter"]
    assert provider["api_key"] == ""
    assert provider["api_key_env"] == "OPENSQUILLA_TEST_IMAGE_KEY"


@pytest.mark.asyncio
async def test_image_generation_configure_can_disable_without_visible_key(
    tmp_path,
    monkeypatch,
):
    target = tmp_path / "c.toml"
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(target))
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    res = await get_dispatcher().dispatch(
        "r1",
        "onboarding.imageGeneration.configure",
        {
            "providerId": "openrouter",
            "primary": "openrouter/google/gemini-3.1-flash-image-preview",
            "enabled": False,
        },
        _admin_ctx(),
    )

    assert res.error is None, res.error
    assert res.payload["entry"]["enabled"] is False
    assert res.payload["entry"]["api_key_source"] == "none"

    data = tomllib.loads(target.read_text())
    assert data["image_generation"]["enabled"] is False


@pytest.mark.asyncio
async def test_onboarding_status_requires_image_generation_enable_for_llm_fallback(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(tmp_path / "c.toml"))
    from opensquilla.gateway.config import GatewayConfig

    ctx = _read_ctx()
    ctx.config = GatewayConfig()
    ctx.config.llm.provider = "openrouter"
    ctx.config.llm.api_key = "sk-or"

    res = await get_dispatcher().dispatch("r1", "onboarding.status", {}, ctx)

    assert res.error is None, res.error
    assert res.payload["imageGenerationConfigured"] is False
    assert res.payload["imageGenerationEnabled"] is False
    assert res.payload["imageGenerationSource"] == "none"
    assert res.payload["imageGenerationProvider"] == ""


@pytest.mark.asyncio
async def test_onboarding_status_exposes_missing_env_keys_for_optional_capabilities(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(tmp_path / "c.toml"))
    from opensquilla.gateway.config import GatewayConfig

    ctx = _read_ctx()
    ctx.config = GatewayConfig()
    ctx.config.llm.provider = "openrouter"
    ctx.config.llm.model = "deepseek/deepseek-v4-flash"
    ctx.config.llm.api_key = "sk-or"
    ctx.config.search_provider = "brave"
    ctx.config.search_api_key_env = "BRAVE_SEARCH_API_KEY"
    ctx.config.image_generation.enabled = True
    ctx.config.image_generation.primary = "openai/gpt-image-1"
    ctx.config.image_generation.providers.openai.api_key_env = "OPENAI_IMAGE_KEY"
    ctx.config.memory.embedding.provider = "openai"
    ctx.config.memory.embedding.remote.api_key_env = "OPENAI_EMBEDDINGS_API_KEY"
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_IMAGE_KEY", raising=False)
    monkeypatch.delenv("OPENAI_EMBEDDINGS_API_KEY", raising=False)

    res = await get_dispatcher().dispatch("r1", "onboarding.status", {}, ctx)

    assert res.error is None, res.error
    assert res.payload["searchProvider"] == "brave"
    assert res.payload["searchSource"] == "missing_env"
    assert res.payload["searchEnvKey"] == "BRAVE_SEARCH_API_KEY"
    assert res.payload["sections"]["image_generation"] == "degraded"
    assert res.payload["sectionDetails"]["image_generation"]["actionRequired"] is True
    assert res.payload["imageGenerationSource"] == "missing_env"
    assert res.payload["imageGenerationProvider"] == "openai"
    assert res.payload["imageGenerationEnvKey"] == "OPENAI_IMAGE_KEY"
    assert res.payload["memoryEmbeddingSource"] == "missing_env"
    assert res.payload["memoryEmbeddingEnvKey"] == "OPENAI_EMBEDDINGS_API_KEY"
    assert res.payload["envRecoveryCommands"] == [
        {
            "section": "memory_embedding",
            "label": "Set memory key",
            "command": _env_hint("OPENAI_EMBEDDINGS_API_KEY"),
        },
        {
            "section": "search",
            "label": "Set search key",
            "command": _env_hint("BRAVE_SEARCH_API_KEY"),
        },
        {
            "section": "image_generation",
            "label": "Set image key",
            "command": _env_hint("OPENAI_IMAGE_KEY"),
        },
    ]


@pytest.mark.asyncio
async def test_image_generation_configure_can_enable_llm_fallback(tmp_path, monkeypatch):
    target = tmp_path / "c.toml"
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(target))
    from opensquilla.gateway.config import GatewayConfig

    ctx = _admin_ctx()
    ctx.config = GatewayConfig()
    ctx.config.llm.provider = "openrouter"
    ctx.config.llm.api_key = "sk-or"

    res = await get_dispatcher().dispatch(
        "r1",
        "onboarding.imageGeneration.configure",
        {"providerId": "openrouter"},
        ctx,
    )

    assert res.error is None, res.error
    assert res.payload["entry"]["enabled"] is True
    assert res.payload["entry"]["api_key_source"] == "llm_fallback"

    data = tomllib.loads(target.read_text())
    assert data["image_generation"]["enabled"] is True
    assert data["image_generation"]["providers"]["openrouter"]["api_key"] == ""


@pytest.mark.asyncio
async def test_memory_embedding_configure_redacts_remote_api_key(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(tmp_path / "c.toml"))
    res = await get_dispatcher().dispatch(
        "r1",
        "onboarding.memory_embedding.configure",
        {
            "providerId": "openai",
            "model": "text-embedding-3-small",
            "apiKey": "mem-secret",
            "baseUrl": "https://api.openai.com/v1",
        },
        _admin_ctx(),
    )
    assert res.error is None, res.error
    assert res.payload["changed"] is True
    assert res.payload["restartRequired"] is True
    assert res.payload["entry"]["remote"]["api_key"] == "***"


@pytest.mark.asyncio
async def test_memory_embedding_configure_can_use_env_key_reference(
    tmp_path,
    monkeypatch,
):
    target = tmp_path / "c.toml"
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(target))

    res = await get_dispatcher().dispatch(
        "r1",
        "onboarding.memory_embedding.configure",
        {
            "providerId": "openai",
            "model": "text-embedding-3-small",
            "apiKeyEnv": "OPENAI_EMBEDDINGS_API_KEY",
        },
        _admin_ctx(),
    )

    assert res.error is None, res.error
    assert res.payload["entry"]["remote"]["api_key_env"] == "OPENAI_EMBEDDINGS_API_KEY"
    data = tomllib.loads(target.read_text())
    remote = data["memory"]["embedding"]["remote"]
    assert remote["api_key_env"] == "OPENAI_EMBEDDINGS_API_KEY"
    assert "api_key" not in remote


@pytest.mark.asyncio
async def test_memory_embedding_configure_updates_ctx_config(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(tmp_path / "c.toml"))
    from opensquilla.gateway.config import GatewayConfig

    ctx = _admin_ctx()
    ctx.config = GatewayConfig()
    ctx.config.config_path = str(tmp_path / "c.toml")

    res = await get_dispatcher().dispatch(
        "r1",
        "onboarding.memory_embedding.configure",
        {"providerId": "local", "onnxDir": "models/bge"},
        ctx,
    )
    assert res.error is None, res.error
    assert ctx.config.memory.embedding.requested_provider == "local"
    assert ctx.config.memory.embedding.local.onnx_dir == "models/bge"


@pytest.mark.asyncio
async def test_memory_embedding_configure_auto_can_store_remote_fallback(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(tmp_path / "c.toml"))
    from opensquilla.gateway.config import GatewayConfig

    ctx = _admin_ctx()
    ctx.config = GatewayConfig()
    ctx.config.config_path = str(tmp_path / "c.toml")

    res = await get_dispatcher().dispatch(
        "r1",
        "onboarding.memory_embedding.configure",
        {
            "providerId": "auto",
            "model": "text-embedding-3-small",
            "apiKey": "mem-secret",
            "baseUrl": "https://embeddings.example/v1",
        },
        ctx,
    )

    assert res.error is None, res.error
    assert ctx.config.memory.embedding.requested_provider == "auto"
    assert ctx.config.memory.embedding.remote.api_key == "mem-secret"
    assert ctx.config.memory.embedding.remote.base_url == "https://embeddings.example/v1"
    assert res.payload["entry"]["remote"]["api_key"] == "***"


@pytest.mark.asyncio
async def test_admin_required_for_mutations(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(tmp_path / "c.toml"))
    res = await get_dispatcher().dispatch(
        "r1",
        "onboarding.provider.configure",
        {"providerId": "openrouter", "model": "x", "apiKey": "k"},
        _read_ctx(),
    )
    assert res.error is not None
    assert res.error.code == "UNAUTHORIZED"


@pytest.mark.asyncio
async def test_provider_configure_writes_to_active_config_path(tmp_path, monkeypatch):
    # Gateway booted from ./opensquilla.toml — RPC must respect ctx.config.config_path.
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(tmp_path / "wrong.toml"))
    project_config = tmp_path / "project.toml"

    from opensquilla.gateway.config import GatewayConfig

    ctx = _admin_ctx()
    ctx.config = GatewayConfig()
    ctx.config.config_path = str(project_config)

    res = await get_dispatcher().dispatch(
        "r1",
        "onboarding.provider.configure",
        {"providerId": "openrouter", "model": "x", "apiKey": "sk-test"},
        ctx,
    )
    assert res.error is None, res.error
    assert project_config.exists()
    assert not (tmp_path / "wrong.toml").exists()
    assert res.payload["configPath"] == str(project_config)


@pytest.mark.asyncio
async def test_provider_configure_updates_ctx_config_in_place(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(tmp_path / "c.toml"))
    from opensquilla.gateway.config import GatewayConfig

    ctx = _admin_ctx()
    ctx.config = GatewayConfig()
    ctx.config.config_path = str(tmp_path / "c.toml")

    await get_dispatcher().dispatch(
        "r1",
        "onboarding.provider.configure",
        {"providerId": "openrouter", "model": "deepseek/x", "apiKey": "sk-new"},
        ctx,
    )
    # The running gateway's config should now reflect the change.
    assert ctx.config.llm.provider == "openrouter"
    assert ctx.config.llm.model == "deepseek/x"
    assert ctx.config.llm.api_key == "sk-new"


@pytest.mark.asyncio
async def test_provider_configure_does_not_persist_runtime_api_key(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(tmp_path / "c.toml"))
    from opensquilla.gateway.config import GatewayConfig

    target = tmp_path / "c.toml"
    ctx = _admin_ctx()
    ctx.config = GatewayConfig()
    ctx.config.config_path = str(target)
    ctx.config.llm.provider = "openrouter"
    ctx.config.llm.model = "m1"
    ctx.config.llm.api_key = "from-env"
    ctx.config.mark_runtime_secret("llm.api_key")

    res = await get_dispatcher().dispatch(
        "r1",
        "onboarding.provider.configure",
        {"providerId": "openrouter", "model": "m2"},
        ctx,
    )

    assert res.error is None, res.error
    data = tomllib.loads(target.read_text())
    assert "api_key" not in data["llm"]
    assert ctx.config.llm.api_key == "from-env"


@pytest.mark.asyncio
async def test_provider_configure_calls_provider_selector_sync(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(tmp_path / "c.toml"))
    from opensquilla.gateway.config import GatewayConfig

    sync_calls: list[object] = []

    class FakeSelector:
        def sync_primary(self, provider_config):
            sync_calls.append(provider_config)

    ctx = _admin_ctx()
    ctx.config = GatewayConfig()
    ctx.config.config_path = str(tmp_path / "c.toml")
    ctx.provider_selector = FakeSelector()

    await get_dispatcher().dispatch(
        "r1",
        "onboarding.provider.configure",
        {"providerId": "openrouter", "model": "m", "apiKey": "k"},
        ctx,
    )
    assert len(sync_calls) == 1
    assert sync_calls[0].provider == "openrouter"
    assert sync_calls[0].model == "m"
    assert sync_calls[0].api_key == "k"


@pytest.mark.asyncio
async def test_provider_configure_syncs_env_key_to_provider_selector(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(tmp_path / "c.toml"))
    monkeypatch.setenv("OPENROUTER_API_KEY", "from-env")
    from opensquilla.gateway.config import GatewayConfig

    sync_calls: list[object] = []

    class FakeSelector:
        def sync_primary(self, provider_config):
            sync_calls.append(provider_config)

    ctx = _admin_ctx()
    ctx.config = GatewayConfig()
    ctx.config.config_path = str(tmp_path / "c.toml")
    ctx.provider_selector = FakeSelector()

    res = await get_dispatcher().dispatch(
        "r1",
        "onboarding.provider.configure",
        {
            "providerId": "openrouter",
            "model": "deepseek/deepseek-v4-flash",
            "apiKeyEnv": "OPENROUTER_API_KEY",
        },
        ctx,
    )

    assert res.error is None, res.error
    assert len(sync_calls) == 1
    assert sync_calls[0].api_key == "from-env"
    assert "llm.api_key" in ctx.config._runtime_secret_paths
    persisted = tomllib.loads((tmp_path / "c.toml").read_text())
    assert "api_key" not in persisted["llm"]


@pytest.mark.asyncio
async def test_channel_disable_then_remove(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(tmp_path / "c.toml"))
    d = get_dispatcher()
    await d.dispatch(
        "r1",
        "onboarding.channel.upsert",
        {"entry": {"type": "slack", "name": "w", "token": "t"}},
        _admin_ctx(),
    )
    res = await d.dispatch("r2", "onboarding.channel.disable", {"name": "w"}, _admin_ctx())
    assert res.error is None
    assert res.payload["enabled"] is False
    res2 = await d.dispatch("r3", "onboarding.channel.remove", {"name": "w"}, _admin_ctx())
    assert res2.error is None
    assert res2.payload["changed"] is True
