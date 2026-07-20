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

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from opensquilla.gateway.config_secrets import inherit_runtime_secrets
from opensquilla.gateway.model_routing import broadcast_model_routing_changed
from opensquilla.gateway.rpc import RpcContext, RpcHandlerError, get_dispatcher
from opensquilla.search.types import DEFAULT_SEARCH_MAX_RESULTS


@contextmanager
def _validation_error(code: str) -> Iterator[None]:
    """Translate a mutation validation error into a stable, client-localizable
    ``RpcHandlerError`` code, keeping the original English text as the message so
    the Web UI can fall back to it (and developers keep the detail).

    Catches both ``ValueError`` (bad fields) and ``KeyError`` (an unknown/
    unverified provider id), since on these onboarding config paths both are user
    validation failures, not internal faults. Other exceptions propagate
    unchanged and still collapse to the dispatcher's coarse codes — only the
    high-value onboarding validation paths are wrapped.
    """
    try:
        yield
    except (ValueError, KeyError) as exc:
        raise RpcHandlerError(code, str(exc)) from exc


@contextmanager
def _channel_error() -> Iterator[None]:
    """Channel mutations raise ``KeyError`` for an unknown name and ``ValueError``
    for bad fields; map them to distinct stable codes."""
    try:
        yield
    except KeyError as exc:
        raise RpcHandlerError("onboarding.channel.not_found", str(exc)) from exc
    except ValueError as exc:
        raise RpcHandlerError("onboarding.channel.invalid", str(exc)) from exc

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
    inherit_runtime_secrets(new_cfg, ctx.config)
    # The mutation clone started from a deep copy of ctx.config's provenance
    # state and then applied the operator's clear_runtime_override /
    # mark_force_persist decisions, so it is authoritative — adopt it
    # wholesale. Without this, a runtime-override record cleared on the
    # clone never reaches the live config, and the stale live record makes a
    # later unrelated persist rewrite the field back to the value the
    # operator just replaced (env-URL / user-URL flip-flops on disk).
    if hasattr(ctx.config, "inherit_persist_provenance") and hasattr(
        new_cfg, "_runtime_field_overrides"
    ):
        ctx.config.inherit_persist_provenance(new_cfg)


def _sync_provider_selector(ctx: RpcContext, llm_cfg: Any) -> None:
    selector = getattr(ctx, "provider_selector", None)
    if selector is None or llm_cfg is None or not hasattr(selector, "sync_primary"):
        return
    config = getattr(ctx, "config", None)
    if config is not None:
        from opensquilla.gateway.llm_runtime import resolve_llm_runtime_config

        # Resolve on a throwaway deep copy: resolve_llm_runtime_config
        # mutates config.llm in place (env application) and records override
        # provenance, but this sync only needs the resolved runtime VALUES
        # for the selector. After _apply_inplace, ctx.config.llm IS the
        # mutation result's llm submodel — resolving against the live graph
        # would clobber an explicit operator base_url/proxy with the env
        # value right before _persist writes the file, and would record the
        # override on ctx.config only, desynchronizing it from the config
        # the persist layer actually consults.
        scratch = config.model_copy(deep=True)
        runtime = resolve_llm_runtime_config(scratch)
        api_key = runtime.api_key
        base_url = runtime.base_url
        proxy = runtime.proxy
        # Preserve the one live-config side effect the old in-place resolve
        # provided: an env-resolved api_key must stay marked as a runtime
        # secret on the running config so no persist path can write it out.
        if runtime.api_key_from_env and hasattr(config, "mark_runtime_secret"):
            config.mark_runtime_secret("llm.api_key")
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
    from opensquilla.tools.builtin.media import configure_audio, configure_image_generation

    configure_image_generation(
        getattr(config, "image_generation", None),
        llm_config=getattr(config, "llm", None),
        squilla_router_config=getattr(config, "squilla_router", None),
    )
    configure_audio(getattr(config, "audio", None))


def _sync_search_provider(config: Any) -> None:
    from opensquilla.tools.builtin.web import configure_search

    configure_search(
        provider_name=config.search_provider,
        max_results=config.search_max_results,
        api_key=config.search_api_key,
        api_key_env=getattr(config, "search_api_key_env", ""),
        proxy=config.search_proxy,
        use_env_proxy=config.search_use_env_proxy,
        fallback_policy=config.search_fallback_policy,
        diagnostics=config.search_diagnostics,
    )


def _persist(ctx: RpcContext, new_cfg: Any, *, restart_required: bool) -> str:
    from opensquilla.onboarding.config_store import persist_config

    # Mutation results are cloned from the active config and carry their own
    # authoritative runtime-secret markers.  Do not re-inherit the live set
    # here: an explicit credential replacement deliberately clears its old
    # env-derived marker so the new value is persisted.  Copying the marker
    # back would silently omit the replacement from disk and keep exposing the
    # startup environment credential through the live settings UI.
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
    from opensquilla.onboarding.legacy_data import legacy_data_payload
    from opensquilla.onboarding.next_steps import env_recovery_commands
    from opensquilla.onboarding.status import get_onboarding_status

    cfg = _active_config(ctx)
    s = get_onboarding_status(cfg)
    llm_credential_status = dict(s.llm_credential_status)
    llm_credential_status["revealAllowed"] = bool(
        ctx.principal.is_owner
        and llm_credential_status.get("available") is True
        and llm_credential_status.get("source") in {"explicit", "env"}
    )
    return {
        "configPath": _config_path_for(ctx, cfg) or s.config_path,
        "hasConfig": s.has_config,
        "llmConfigured": s.llm_configured,
        "llmSource": s.llm_source,
        "llmEnvKey": s.llm_env_key,
        "llmCredentialStatus": llm_credential_status,
        "imageGenerationConfigured": s.image_generation_configured,
        "imageGenerationEnabled": s.image_generation_enabled,
        "imageGenerationSource": s.image_generation_source,
        "imageGenerationProvider": s.image_generation_provider,
        "imageGenerationPrimary": s.image_generation_primary,
        "imageGenerationEnvKey": s.image_generation_env_key,
        "audioConfigured": s.audio_configured,
        "audioEnabled": s.audio_enabled,
        "audioSource": s.audio_source,
        "audioProvider": s.audio_provider,
        "audioEnvKey": s.audio_env_key,
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
        "ensembleCredentialStatus": list(s.ensemble_credential_status),
        "needsOnboarding": s.needs_onboarding,
        "sections": {name: state.value for name, state in s.sections.items()},
        "sectionDetails": s.section_details,
        "envRecoveryCommands": env_recovery_commands(s),
        "warnings": list(s.warnings),
        # Read-only legacy-home advisory for the Web UI setup flow; execution
        # stays at the CLI layer (the block carries the command to run).
        "legacyData": legacy_data_payload(),
    }


def _active_llm_credential_reveal_payload(ctx: RpcContext, provider_id: str) -> dict[str, Any]:
    from opensquilla.onboarding.provider_specs import get_provider_setup_spec

    if not ctx.principal.is_owner:
        raise RpcHandlerError(
            "onboarding.provider.credential.not_owner",
            "Only the local gateway owner can reveal provider credentials.",
        )

    cfg = _active_config(ctx)
    llm = getattr(cfg, "llm", None)
    active_provider = str(getattr(llm, "provider", "") or "").strip().lower()
    requested_provider = str(provider_id or "").strip().lower()
    if requested_provider != active_provider:
        raise RpcHandlerError(
            "onboarding.provider.credential.inactive_provider",
            "Credential reveal only supports the active provider.",
        )

    try:
        spec = get_provider_setup_spec(active_provider)
    except KeyError as exc:
        raise RpcHandlerError(
            "onboarding.provider.credential.unsupported_provider",
            f"Unsupported active provider: {active_provider}",
        ) from exc
    env_key = (
        str(getattr(llm, "api_key_env", "") or "").strip()
        or str(getattr(spec, "env_key", "") or "").strip()
    )
    runtime_secret_paths: set[str] = getattr(cfg, "_runtime_secret_paths", set())
    explicit_key = (
        ""
        if "llm.api_key" in runtime_secret_paths
        else str(getattr(llm, "api_key", "") or "")
    )
    if explicit_key:
        return {
            "ok": True,
            "provider": active_provider,
            "source": "explicit",
            "envKey": env_key,
            "apiKey": explicit_key,
        }
    if env_key:
        env_value = str(os.environ.get(env_key) or "")
        if env_value:
            return {
                "ok": True,
                "provider": active_provider,
                "source": "env",
                "envKey": env_key,
                "apiKey": env_value,
            }
    raise RpcHandlerError(
        "onboarding.provider.credential.unavailable",
        "No revealable credential is available for the active provider.",
    )


@_d.method("onboarding.status", scope="operator.read")
async def _onboarding_status(params: Any, ctx: RpcContext) -> dict[str, Any]:
    return _status_payload(ctx)


@_d.method("onboarding.catalog", scope="operator.read")
async def _onboarding_catalog(params: Any, ctx: RpcContext) -> dict[str, Any]:
    from opensquilla.onboarding.audio_specs import audio_provider_catalog_payload
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
        "audioProviders": audio_provider_catalog_payload(),
    }


def _require(params: Any, key: str) -> Any:
    if not isinstance(params, dict) or key not in params:
        raise ValueError(f"params.{key} is required")
    return params[key]


def _param(params: Any, key: str, default: Any) -> Any:
    """``params.get`` that also maps an explicit JSON ``null`` to ``default``.

    The onboarding mutations widened several parameters to ``None`` =
    keep-current for the CLI, but over RPC the legacy contract is pinned:
    an absent key AND an explicit ``null`` both mean the legacy default
    (reset/derive/clear), so hand-written clients sending ``null`` keep the
    pre-widening behavior instead of silently keeping stored values.
    """
    if not isinstance(params, dict):
        return default
    value = params.get(key, default)
    return default if value is None else value


def _bool_param(params: Any, key: str, default: bool = False) -> bool:
    value = _param(params, key, default)
    if not isinstance(value, bool):
        raise ValueError(f"params.{key} must be a boolean")
    return value


def _provider_candidate_identity(
    cfg: Any,
    provider_id: str,
    candidate_base_url: str,
) -> tuple[bool, bool]:
    """Return ``(same_provider, stored_credentials_may_be_reused)``."""
    from opensquilla.onboarding.endpoint_identity import (
        base_url_allows_credential_reuse,
    )

    active_provider = str(getattr(cfg.llm, "provider", "") or "").strip().lower()
    requested_provider = str(provider_id or "").strip().lower()
    same_provider = active_provider == requested_provider
    return same_provider, same_provider and base_url_allows_credential_reuse(
        str(getattr(cfg.llm, "base_url", "") or ""),
        candidate_base_url,
    )


@_d.method("onboarding.provider.configure", scope="operator.admin")
async def _provider_configure(params: Any, ctx: RpcContext) -> dict[str, Any]:
    from opensquilla.onboarding.mutations import upsert_llm_provider

    provider_id = _require(params, "providerId")
    # Legacy null semantics pinned: absent key OR explicit null = legacy
    # default ("" -> derive/reset), never keep-current (see _param).
    model = _param(params, "model", "")
    cfg = _active_config(ctx)
    with _validation_error("onboarding.provider.invalid"):
        res = upsert_llm_provider(
            cfg,
            provider_id=provider_id,
            model=model,
            api_key=_param(params, "apiKey", ""),
            api_key_env=_param(params, "apiKeyEnv", ""),
            preserve_api_key=_bool_param(params, "preserveApiKey"),
            base_url=_param(params, "baseUrl", ""),
            proxy=_param(params, "proxy", ""),
            # Explicit-user-action only (D18): a preset is applied exactly when
            # the client sends presetId; a plain save never auto-applies one.
            preset_id=_param(params, "presetId", ""),
        )
    # Persist first: if the write fails, the live config is untouched and
    # memory/disk stay consistent. Tool syncs run only on applied state.
    config_path = _persist(ctx, res.config, restart_required=res.restart_required)
    _apply_inplace(ctx, res.config)
    _sync_provider_selector(ctx, res.config.llm)
    _sync_image_generation(res.config)
    # Provider saves are an explicit retry boundary for registry-declared
    # public model listings. Await the bounded best-effort refresh so the next
    # turn observes the new catalog without requiring a gateway restart.
    from opensquilla.gateway.model_catalog_refresh import refresh_live_model_catalog

    await refresh_live_model_catalog(ctx.config if ctx.config is not None else res.config)
    return {
        "changed": res.changed,
        "restartRequired": res.restart_required,
        "configPath": config_path,
        "entry": res.public_payload,
        "warnings": res.warnings,
    }


@_d.method("onboarding.provider.probe", scope="operator.admin")
async def _provider_probe(params: Any, ctx: RpcContext) -> dict[str, Any]:
    """Live one-token probe of a candidate provider config (nothing is saved)."""
    from opensquilla.onboarding.probe import probe_llm_provider

    provider_id = _require(params, "providerId")
    p = params if isinstance(params, dict) else {}
    cfg = _active_config(ctx)
    api_key = str(p.get("apiKey", "") or "")
    api_key_env = str(p.get("apiKeyEnv", "") or "")
    base_url = str(p.get("baseUrl", "") or "")
    proxy = str(p.get("proxy", "") or "")
    # A provider id is not an endpoint identity for configurable providers.
    # Stored credentials may follow an omitted URL or a same-origin path
    # change, but never a scheme/host/effective-port change.
    same_provider, reuse_stored_credentials = _provider_candidate_identity(
        cfg,
        str(provider_id),
        base_url,
    )
    if same_provider:
        if not api_key and not api_key_env and reuse_stored_credentials:
            api_key = str(getattr(cfg.llm, "api_key", "") or "")
            api_key_env = str(getattr(cfg.llm, "api_key_env", "") or "")
        if not base_url:
            base_url = str(getattr(cfg.llm, "base_url", "") or "")
        if not proxy:
            proxy = str(getattr(cfg.llm, "proxy", "") or "")
    with _validation_error("onboarding.provider.invalid"):
        result = await probe_llm_provider(
            provider_id=provider_id,
            model=str(p.get("model", "") or ""),
            api_key=api_key,
            api_key_env=api_key_env,
            base_url=base_url,
            proxy=proxy,
            allow_default_api_key_env=(
                not same_provider or reuse_stored_credentials
            ),
        )
    return result.to_payload()


@_d.method("onboarding.provider.credential.reveal", scope="operator.admin")
async def _provider_credential_reveal(params: Any, ctx: RpcContext) -> dict[str, Any]:
    provider_id = _require(params, "providerId")
    return _active_llm_credential_reveal_payload(ctx, provider_id)


@_d.method("onboarding.models.discover", scope="operator.admin")
async def _models_discover(params: Any, ctx: RpcContext) -> dict[str, Any]:
    """List verified picker-safe models without persisting anything.

    Admin-scoped (like ``onboarding.provider.probe``): the request carries
    candidate credentials, so it must not be reachable at the read/write
    tiers even though it changes no state.

    Selector discovery is fail-closed: only registry-verified providers on
    their official hosts are queried. Self-hosted and arbitrary endpoints
    remain manual-entry surfaces; raw CLI diagnostics retain their broader
    endpoint-probing behavior.

    Blank credentials fall back to the stored config's only while a supplied
    candidate Base URL remains same-origin; omitted Base URLs reuse the stored
    endpoint.
    """
    from opensquilla.onboarding.probe import discover_selectable_provider_models

    provider_id = _require(params, "providerId")
    p = params if isinstance(params, dict) else {}
    cfg = _active_config(ctx)
    api_key = str(p.get("apiKey", "") or "")
    api_key_env = str(p.get("apiKeyEnv", "") or "")
    base_url = str(p.get("baseUrl", "") or "")
    proxy = str(p.get("proxy", "") or "")
    same_provider, reuse_stored_credentials = _provider_candidate_identity(
        cfg,
        str(provider_id),
        base_url,
    )
    if same_provider:
        if not api_key and not api_key_env and reuse_stored_credentials:
            api_key = str(getattr(cfg.llm, "api_key", "") or "")
            api_key_env = str(getattr(cfg.llm, "api_key_env", "") or "")
        if not base_url:
            base_url = str(getattr(cfg.llm, "base_url", "") or "")
        if not proxy:
            proxy = str(getattr(cfg.llm, "proxy", "") or "")
    with _validation_error("onboarding.provider.invalid"):
        result = await discover_selectable_provider_models(
            provider_id=provider_id,
            api_key=api_key,
            api_key_env=api_key_env,
            base_url=base_url,
            proxy=proxy,
            allow_default_api_key_env=(
                not same_provider or reuse_stored_credentials
            ),
        )
    return result.to_payload()


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
    cross_provider_tiers = params.get("crossProviderTiers") if isinstance(params, dict) else None
    tier_provider_mismatch = (
        params.get("tierProviderMismatch") if isinstance(params, dict) else None
    )
    with _validation_error("onboarding.router.invalid"):
        res = upsert_router(
            cfg,
            mode=mode,
            default_tier=default_tier,
            tiers=tiers,
            cross_provider_tiers=cross_provider_tiers,
            tier_provider_mismatch=tier_provider_mismatch,
        )
    # Persist first: if the write fails, the live config is untouched and
    # memory/disk stay consistent. Tool syncs run only on applied state.
    config_path = _persist(ctx, res.config, restart_required=res.restart_required)
    _apply_inplace(ctx, res.config)
    _sync_provider_selector(ctx, res.config.llm)
    await broadcast_model_routing_changed(
        ctx,
        source="onboarding.router.configure",
        config=res.config,
    )
    return {
        "changed": res.changed,
        "restartRequired": res.restart_required,
        "configPath": config_path,
        "entry": res.public_payload,
        "warnings": res.warnings,
    }


@_d.method("onboarding.ensemble.configure", scope="operator.admin")
async def _ensemble_configure(params: Any, ctx: RpcContext) -> dict[str, Any]:
    """Configure the [llm_ensemble] routing surface.

    Omitted params keep the current value (partial-payload merge in the
    mutation); the TurnRunner reads llm_ensemble live, so no restart.
    """
    from opensquilla.onboarding.mutations import upsert_llm_ensemble

    cfg = _active_config(ctx)
    p = params if isinstance(params, dict) else {}
    with _validation_error("onboarding.ensemble.invalid"):
        res = upsert_llm_ensemble(
            cfg,
            enabled=p.get("enabled"),
            selection_mode=p.get("selectionMode"),
            model_options=p.get("modelOptions"),
            candidates=p.get("candidates"),
            min_successful_proposers=p.get("minSuccessfulProposers"),
            all_failed_policy=p.get("allFailedPolicy"),
        )
    # Persist first: if the write fails, the live config is untouched and
    # memory/disk stay consistent. Tool syncs run only on applied state.
    config_path = _persist(ctx, res.config, restart_required=res.restart_required)
    _apply_inplace(ctx, res.config)
    await broadcast_model_routing_changed(
        ctx,
        source="onboarding.ensemble.configure",
        config=res.config,
    )
    return {
        "changed": res.changed,
        "restartRequired": res.restart_required,
        "configPath": config_path,
        "entry": res.public_payload,
        "warnings": res.warnings,
    }


@_d.method("onboarding.channel.probe", scope="operator.admin")
async def _channel_probe(params: Any, ctx: RpcContext) -> dict[str, Any]:
    from opensquilla.onboarding.mutations import (
        merge_channel_entry_secrets,
        validate_channel_entry,
    )
    from opensquilla.onboarding.redaction import redact_channel_entry

    entry = _require(params, "entry")
    if not isinstance(entry, dict):
        raise ValueError("params.entry must be an object")
    # Merge-aware probe: blank secrets resolve against the stored entry the
    # same way onboarding.channel.upsert does, so probing a keep-current
    # payload validates the entry the upsert would actually persist instead
    # of hard-failing on the non-blank-secret requirement. A genuinely blank
    # secret (no stored entry to merge from) still fails validation.
    cfg = _active_config(ctx)
    with _channel_error():
        normalized = validate_channel_entry(merge_channel_entry_secrets(cfg, entry))
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
    with _validation_error("onboarding.search.invalid"):
        res = upsert_search_provider(
            cfg,
            provider_id=provider_id,
            # Legacy null semantics pinned: absent key OR explicit null maps
            # to the legacy default (reset/clear), never keep-current.
            api_key=_param(params, "apiKey", ""),
            api_key_env=_param(params, "apiKeyEnv", ""),
            max_results=_param(params, "maxResults", DEFAULT_SEARCH_MAX_RESULTS),
            proxy=_param(params, "proxy", ""),
            use_env_proxy=_param(params, "useEnvProxy", False),
            fallback_policy=_param(params, "fallbackPolicy", "off"),
            diagnostics=_param(params, "diagnostics", False),
        )
    # Persist first: if the write fails, the live config is untouched and
    # memory/disk stay consistent. Tool syncs run only on applied state.
    config_path = _persist(ctx, res.config, restart_required=res.restart_required)
    _apply_inplace(ctx, res.config)
    _sync_search_provider(res.config)
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
    fallbacks = params.get("fallbacks") if isinstance(params, dict) else None
    with _validation_error("onboarding.imageGeneration.invalid"):
        res = upsert_image_generation_provider(
            cfg,
            provider_id=provider_id,
            primary=params.get("primary", "") if isinstance(params, dict) else "",
            api_key=params.get("apiKey", "") if isinstance(params, dict) else "",
            api_key_env=params.get("apiKeyEnv", "") if isinstance(params, dict) else "",
            base_url=params.get("baseUrl", "") if isinstance(params, dict) else "",
            enabled=params.get("enabled", True) if isinstance(params, dict) else True,
            size=params.get("size", "") if isinstance(params, dict) else "",
            output_format=params.get("outputFormat", "") if isinstance(params, dict) else "",
            fallbacks=list(fallbacks) if isinstance(fallbacks, list) else None,
        )
    # Persist first: if the write fails, the live config is untouched and
    # memory/disk stay consistent. Tool syncs run only on applied state.
    config_path = _persist(ctx, res.config, restart_required=res.restart_required)
    _apply_inplace(ctx, res.config)
    _sync_image_generation(res.config)
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
    # Persist first: if the write fails, the live config is untouched and
    # memory/disk stay consistent. Tool syncs run only on applied state.
    config_path = _persist(ctx, res.config, restart_required=res.restart_required)
    _apply_inplace(ctx, res.config)
    return {
        "changed": res.changed,
        "restartRequired": res.restart_required,
        "configPath": config_path,
        "entry": res.public_payload,
        "warnings": res.warnings,
    }


@_d.method("onboarding.audio.configure", scope="operator.admin")
async def _audio_configure(params: Any, ctx: RpcContext) -> dict[str, Any]:
    from opensquilla.onboarding.mutations import upsert_audio_provider

    provider_id = _require(params, "providerId")
    cfg = _active_config(ctx)
    res = upsert_audio_provider(
        cfg,
        provider_id=provider_id,
        api_key=params.get("apiKey", "") if isinstance(params, dict) else "",
        api_key_env=params.get("apiKeyEnv", "") if isinstance(params, dict) else "",
        base_url=params.get("baseUrl", "") if isinstance(params, dict) else "",
        enabled=params.get("enabled", True) if isinstance(params, dict) else True,
        tts_voice=params.get("ttsVoice", "") if isinstance(params, dict) else "",
        tts_model=params.get("ttsModel", "") if isinstance(params, dict) else "",
        language_code=params.get("languageCode", "") if isinstance(params, dict) else "",
    )
    # Persist first: if the write fails, the live config is untouched and
    # memory/disk stay consistent. Tool syncs run only on applied state.
    config_path = _persist(ctx, res.config, restart_required=res.restart_required)
    _apply_inplace(ctx, res.config)
    _sync_image_generation(res.config)
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
    with _channel_error():
        res = upsert_channel(cfg, entry_payload=entry)
    # Persist first: if the write fails, the live config is untouched and
    # memory/disk stay consistent. Tool syncs run only on applied state.
    config_path = _persist(ctx, res.config, restart_required=True)
    _apply_inplace(ctx, res.config)
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
    with _channel_error():
        res = remove_channel(cfg, name=name)
    # Persist first: if the write fails, the live config is untouched and
    # memory/disk stay consistent. Tool syncs run only on applied state.
    config_path = _persist(ctx, res.config, restart_required=True)
    _apply_inplace(ctx, res.config)
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
    with _channel_error():
        res = set_channel_enabled(cfg, name=name, enabled=enabled)
    # Persist first: if the write fails, the live config is untouched and
    # memory/disk stay consistent. Tool syncs run only on applied state.
    config_path = _persist(ctx, res.config, restart_required=True)
    _apply_inplace(ctx, res.config)
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
