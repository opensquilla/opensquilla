"""RPC handlers for onboarding (catalog, status, provider/channel mutations).

Mutations are applied against the gateway's *active* in-memory config when the
RPC context provides one (``ctx.config``). The same context exposes the
running ``provider_selector``; provider mutations are mirrored into it so a
``configure`` from the WebUI takes effect on the next chat without a restart.

Channel mutations always require a restart because ``ChannelManager`` is built
once at boot.

The onboarding mutation/store modules import ``opensquilla.gateway.config`` at
module top level, which transitively re-enters ``opensquilla.gateway`` during
boot. To avoid the circular import, we import those bindings lazily inside the
handler bodies.
"""

from __future__ import annotations

from typing import Any

from opensquilla.gateway.rpc import RpcContext, get_dispatcher

_d = get_dispatcher()


def _active_config(ctx: RpcContext) -> Any:
    """Return the gateway's running config when available, else load from disk."""
    if ctx.config is not None:
        return ctx.config
    from opensquilla.onboarding.config_store import load_config

    return load_config()


def _config_path_for(ctx: RpcContext, source: Any) -> str | None:
    """Resolve the persistence path that matches ``source``.

    Prefers the path stored on the running ``GatewayConfig`` so RPCs save back
    to wherever the gateway booted from (e.g. ``./opensquilla.toml``) rather
    than the env-default user config.
    """
    path = getattr(source, "config_path", None)
    if path:
        return str(path)
    return None


def _apply_inplace(ctx: RpcContext, new_cfg: Any) -> None:
    """Mirror new config fields into ``ctx.config`` so the running gateway sees them."""
    if ctx.config is None or ctx.config is new_cfg:
        return
    for field_name in type(new_cfg).model_fields:
        setattr(ctx.config, field_name, getattr(new_cfg, field_name))
    if hasattr(ctx.config, "inherit_runtime_secrets"):
        ctx.config.inherit_runtime_secrets(new_cfg)


def _sync_provider_selector(ctx: RpcContext, llm_cfg: Any) -> None:
    selector = getattr(ctx, "provider_selector", None)
    if selector is None or llm_cfg is None or not hasattr(selector, "sync_primary"):
        return
    config = getattr(ctx, "config", None)
    if config is not None:
        from opensquilla.gateway.llm_runtime import resolve_llm_runtime_config

        runtime = resolve_llm_runtime_config(config)
        api_key = runtime.api_key
        base_url = runtime.base_url
        proxy = runtime.proxy
    else:
        api_key = llm_cfg.api_key
        base_url = llm_cfg.base_url
        proxy = getattr(llm_cfg, "proxy", "")
    from opensquilla.provider.selector import ProviderConfig

    selector.sync_primary(
        ProviderConfig(
            provider=llm_cfg.provider,
            model=llm_cfg.model,
            api_key=api_key,
            base_url=base_url,
            proxy=proxy,
            provider_routing=getattr(llm_cfg, "provider_routing", {}),
        )
    )


def _sync_image_generation(config: Any) -> None:
    from opensquilla.tools.builtin.media import configure_image_generation

    configure_image_generation(
        getattr(config, "image_generation", None),
        llm_config=getattr(config, "llm", None),
        squilla_router_config=getattr(config, "squilla_router", None),
    )


def _sync_search_provider(config: Any) -> None:
    from opensquilla.tools.builtin.web import configure_search

    configure_search(
        provider_name=config.search_provider,
        max_results=config.search_max_results,
        api_key=config.search_api_key,
        proxy=config.search_proxy,
        use_env_proxy=config.search_use_env_proxy,
        fallback_policy=config.search_fallback_policy,
        diagnostics=config.search_diagnostics,
    )


def _persist(ctx: RpcContext, new_cfg: Any, *, restart_required: bool) -> str:
    from opensquilla.onboarding.config_store import persist_config

    if (
        ctx.config is not None
        and ctx.config is not new_cfg
        and hasattr(new_cfg, "inherit_runtime_secrets")
    ):
        new_cfg.inherit_runtime_secrets(ctx.config)
    path = _config_path_for(ctx, new_cfg) or _config_path_for(ctx, ctx.config)
    persist = persist_config(new_cfg, path=path, restart_required=restart_required)
    # Preserve the resolved path on the running config so subsequent saves
    # round-trip to the same file.
    if hasattr(new_cfg, "config_path") and not getattr(new_cfg, "config_path", None):
        new_cfg.config_path = str(persist.path)
    if (
        ctx.config is not None
        and hasattr(ctx.config, "config_path")
        and not getattr(ctx.config, "config_path", None)
    ):
        ctx.config.config_path = str(persist.path)
    return str(persist.path)


def _status_payload(ctx: RpcContext) -> dict[str, Any]:
    from opensquilla.onboarding.next_steps import env_recovery_commands
    from opensquilla.onboarding.status import get_onboarding_status

    cfg = _active_config(ctx)
    s = get_onboarding_status(cfg)
    return {
        "configPath": _config_path_for(ctx, cfg) or s.config_path,
        "hasConfig": s.has_config,
        "llmConfigured": s.llm_configured,
        "llmSource": s.llm_source,
        "llmEnvKey": s.llm_env_key,
        "imageGenerationConfigured": s.image_generation_configured,
        "imageGenerationEnabled": s.image_generation_enabled,
        "imageGenerationSource": s.image_generation_source,
        "imageGenerationProvider": s.image_generation_provider,
        "imageGenerationPrimary": s.image_generation_primary,
        "imageGenerationEnvKey": s.image_generation_env_key,
        "searchConfigured": s.search_configured,
        "searchProvider": s.search_provider,
        "searchSource": s.search_source,
        "searchEnvKey": s.search_env_key,
        "memoryEmbeddingConfigured": s.memory_embedding_configured,
        "memoryEmbeddingProvider": s.memory_embedding_provider,
        "memoryEmbeddingSource": s.memory_embedding_source,
        "memoryEmbeddingEnvKey": s.memory_embedding_env_key,
        "channelCount": s.channel_count,
        "channelsConfigured": s.channels_configured,
        "needsOnboarding": s.needs_onboarding,
        "sections": {name: state.value for name, state in s.sections.items()},
        "sectionDetails": s.section_details,
        "envRecoveryCommands": env_recovery_commands(s),
        "warnings": list(s.warnings),
    }


@_d.method("onboarding.status", scope="operator.read")
async def _onboarding_status(params: Any, ctx: RpcContext) -> dict[str, Any]:
    return _status_payload(ctx)


@_d.method("onboarding.catalog", scope="operator.read")
async def _onboarding_catalog(params: Any, ctx: RpcContext) -> dict[str, Any]:
    from opensquilla.onboarding.channel_specs import channel_catalog_payload
    from opensquilla.onboarding.image_generation_specs import (
        image_generation_provider_catalog_payload,
    )
    from opensquilla.onboarding.memory_embedding_specs import (
        memory_embedding_provider_catalog_payload,
    )
    from opensquilla.onboarding.provider_specs import provider_catalog_payload
    from opensquilla.onboarding.router_specs import router_catalog_payload
    from opensquilla.onboarding.search_specs import search_provider_catalog_payload

    return {
        "providers": provider_catalog_payload(),
        "channels": channel_catalog_payload(),
        "searchProviders": search_provider_catalog_payload(),
        "routerProfiles": router_catalog_payload(),
        "memoryEmbeddingProviders": memory_embedding_provider_catalog_payload(),
        "imageGenerationProviders": image_generation_provider_catalog_payload(),
    }


def _require(params: Any, key: str) -> Any:
    if not isinstance(params, dict) or key not in params:
        raise ValueError(f"params.{key} is required")
    return params[key]


@_d.method("onboarding.provider.configure", scope="operator.admin")
async def _provider_configure(params: Any, ctx: RpcContext) -> dict[str, Any]:
    from opensquilla.onboarding.mutations import upsert_llm_provider

    provider_id = _require(params, "providerId")
    model = params.get("model", "") if isinstance(params, dict) else ""
    cfg = _active_config(ctx)
    res = upsert_llm_provider(
        cfg,
        provider_id=provider_id,
        model=model,
        api_key=params.get("apiKey", "") if isinstance(params, dict) else "",
        api_key_env=params.get("apiKeyEnv", "") if isinstance(params, dict) else "",
        base_url=params.get("baseUrl", "") if isinstance(params, dict) else "",
        proxy=params.get("proxy", "") if isinstance(params, dict) else "",
    )
    _apply_inplace(ctx, res.config)
    _sync_provider_selector(ctx, res.config.llm)
    _sync_image_generation(res.config)
    config_path = _persist(ctx, res.config, restart_required=res.restart_required)
    return {
        "changed": res.changed,
        "restartRequired": res.restart_required,
        "configPath": config_path,
        "entry": res.public_payload,
        "warnings": res.warnings,
    }


@_d.method("onboarding.router.catalog", scope="operator.read")
async def _router_catalog(params: Any, ctx: RpcContext) -> dict[str, Any]:
    from opensquilla.onboarding.router_specs import router_catalog_payload

    return router_catalog_payload()


@_d.method("onboarding.router.configure", scope="operator.admin")
async def _router_configure(params: Any, ctx: RpcContext) -> dict[str, Any]:
    from opensquilla.onboarding.mutations import upsert_router

    cfg = _active_config(ctx)
    mode = params.get("mode", "recommended") if isinstance(params, dict) else "recommended"
    default_tier = params.get("defaultTier") if isinstance(params, dict) else None
    tiers = params.get("tiers") if isinstance(params, dict) else None
    res = upsert_router(cfg, mode=mode, default_tier=default_tier, tiers=tiers)
    _apply_inplace(ctx, res.config)
    _sync_provider_selector(ctx, res.config.llm)
    config_path = _persist(ctx, res.config, restart_required=res.restart_required)
    return {
        "changed": res.changed,
        "restartRequired": res.restart_required,
        "configPath": config_path,
        "entry": res.public_payload,
        "warnings": res.warnings,
    }


@_d.method("onboarding.channel.probe", scope="operator.admin")
async def _channel_probe(params: Any, ctx: RpcContext) -> dict[str, Any]:
    from opensquilla.onboarding.mutations import validate_channel_entry
    from opensquilla.onboarding.redaction import redact_channel_entry

    entry = _require(params, "entry")
    if not isinstance(entry, dict):
        raise ValueError("params.entry must be an object")
    normalized = validate_channel_entry(entry)
    type_name = str(normalized.get("type") or "")
    return {
        "status": "ready",
        "connected": False,
        "restartRequired": True,
        "entry": redact_channel_entry(type_name, normalized),
        "warnings": [],
    }


@_d.method("onboarding.search.configure", scope="operator.admin")
async def _search_configure(params: Any, ctx: RpcContext) -> dict[str, Any]:
    from opensquilla.onboarding.mutations import upsert_search_provider

    provider_id = _require(params, "providerId")
    cfg = _active_config(ctx)
    res = upsert_search_provider(
        cfg,
        provider_id=provider_id,
        api_key=params.get("apiKey", "") if isinstance(params, dict) else "",
        api_key_env=params.get("apiKeyEnv", "") if isinstance(params, dict) else "",
        max_results=params.get("maxResults", 5) if isinstance(params, dict) else 5,
        proxy=params.get("proxy", "") if isinstance(params, dict) else "",
        use_env_proxy=(params.get("useEnvProxy", False) if isinstance(params, dict) else False),
        fallback_policy=(
            params.get("fallbackPolicy", "off") if isinstance(params, dict) else "off"
        ),
        diagnostics=params.get("diagnostics", False) if isinstance(params, dict) else False,
    )
    _apply_inplace(ctx, res.config)
    _sync_search_provider(res.config)
    config_path = _persist(ctx, res.config, restart_required=res.restart_required)
    return {
        "changed": res.changed,
        "restartRequired": res.restart_required,
        "configPath": config_path,
        "entry": res.public_payload,
        "warnings": res.warnings,
    }


@_d.method("onboarding.imageGeneration.configure", scope="operator.admin")
async def _image_generation_configure(params: Any, ctx: RpcContext) -> dict[str, Any]:
    from opensquilla.onboarding.mutations import upsert_image_generation_provider

    provider_id = _require(params, "providerId")
    cfg = _active_config(ctx)
    res = upsert_image_generation_provider(
        cfg,
        provider_id=provider_id,
        primary=params.get("primary", "") if isinstance(params, dict) else "",
        api_key=params.get("apiKey", "") if isinstance(params, dict) else "",
        api_key_env=params.get("apiKeyEnv", "") if isinstance(params, dict) else "",
        base_url=params.get("baseUrl", "") if isinstance(params, dict) else "",
        enabled=params.get("enabled", True) if isinstance(params, dict) else True,
    )
    _apply_inplace(ctx, res.config)
    _sync_image_generation(res.config)
    config_path = _persist(ctx, res.config, restart_required=res.restart_required)
    return {
        "changed": res.changed,
        "restartRequired": res.restart_required,
        "configPath": config_path,
        "entry": res.public_payload,
        "warnings": res.warnings,
    }


@_d.method("onboarding.memory_embedding.configure", scope="operator.admin")
async def _memory_embedding_configure(params: Any, ctx: RpcContext) -> dict[str, Any]:
    from opensquilla.onboarding.mutations import upsert_memory_embedding

    provider = _require(params, "providerId")
    cfg = _active_config(ctx)
    res = upsert_memory_embedding(
        cfg,
        provider=provider,
        model=params.get("model", "") if isinstance(params, dict) else "",
        api_key=params.get("apiKey", "") if isinstance(params, dict) else "",
        api_key_env=params.get("apiKeyEnv", "") if isinstance(params, dict) else "",
        base_url=params.get("baseUrl", "") if isinstance(params, dict) else "",
        onnx_dir=params.get("onnxDir", "") if isinstance(params, dict) else "",
    )
    _apply_inplace(ctx, res.config)
    config_path = _persist(ctx, res.config, restart_required=res.restart_required)
    return {
        "changed": res.changed,
        "restartRequired": res.restart_required,
        "configPath": config_path,
        "entry": res.public_payload,
        "warnings": res.warnings,
    }


@_d.method("onboarding.channel.upsert", scope="operator.admin")
async def _channel_upsert(params: Any, ctx: RpcContext) -> dict[str, Any]:
    from opensquilla.onboarding.mutations import upsert_channel

    entry = _require(params, "entry")
    if not isinstance(entry, dict):
        raise ValueError("params.entry must be an object")
    cfg = _active_config(ctx)
    res = upsert_channel(cfg, entry_payload=entry)
    _apply_inplace(ctx, res.config)
    config_path = _persist(ctx, res.config, restart_required=True)
    return {
        "changed": res.changed,
        "restartRequired": True,
        "configPath": config_path,
        "entry": res.public_payload,
        "warnings": res.warnings,
    }


@_d.method("onboarding.channel.remove", scope="operator.admin")
async def _channel_remove(params: Any, ctx: RpcContext) -> dict[str, Any]:
    from opensquilla.onboarding.mutations import remove_channel

    name = _require(params, "name")
    cfg = _active_config(ctx)
    res = remove_channel(cfg, name=name)
    _apply_inplace(ctx, res.config)
    config_path = _persist(ctx, res.config, restart_required=True)
    return {
        "changed": res.changed,
        "restartRequired": True,
        "configPath": config_path,
        "removed": name,
    }


async def _toggle(ctx: RpcContext, params: Any, enabled: bool) -> dict[str, Any]:
    from opensquilla.onboarding.mutations import set_channel_enabled

    name = _require(params, "name")
    cfg = _active_config(ctx)
    res = set_channel_enabled(cfg, name=name, enabled=enabled)
    _apply_inplace(ctx, res.config)
    config_path = _persist(ctx, res.config, restart_required=True)
    return {
        "changed": res.changed,
        "restartRequired": True,
        "configPath": config_path,
        "name": name,
        "enabled": enabled,
    }


@_d.method("onboarding.channel.enable", scope="operator.admin")
async def _channel_enable(params: Any, ctx: RpcContext) -> dict[str, Any]:
    return await _toggle(ctx, params, True)


@_d.method("onboarding.channel.disable", scope="operator.admin")
async def _channel_disable(params: Any, ctx: RpcContext) -> dict[str, Any]:
    return await _toggle(ctx, params, False)
