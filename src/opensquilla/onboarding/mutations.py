"""Mutations for provider/channel onboarding configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Literal, cast

from pydantic import ValidationError

from opensquilla.channels.registry import discover_all, parse_channel_entry
from opensquilla.gateway.config import (
    ROUTER_TIER_PROFILE_IDS,
    ChannelsConfig,
    GatewayConfig,
    LlmProviderConfig,
    MemoryEmbeddingConfig,
    SquillaRouterConfig,
    _router_tier_profile_defaults,
)
from opensquilla.onboarding.audio_specs import get_audio_provider_setup_spec
from opensquilla.onboarding.image_generation_specs import (
    get_image_generation_provider_setup_spec,
)
from opensquilla.onboarding.provider_specs import get_provider_setup_spec
from opensquilla.onboarding.redaction import (
    redact_audio_payload,
    redact_channel_entry,
    redact_image_generation_payload,
    redact_memory_embedding_payload,
    redact_provider_payload,
    redact_search_payload,
)
from opensquilla.onboarding.search_specs import get_search_provider_setup_spec
from opensquilla.router_tiers import (
    DEFAULT_TEXT_TIER,
    TEXT_TIERS,
    normalize_text_tier,
)
from opensquilla.secrets import clean_header_secret

SearchFallbackPolicy = Literal["off", "network"]
RouterMode = Literal["recommended", "openrouter-mix", "disabled"]
_TEXT_ROUTER_TIERS = TEXT_TIERS
_ROUTER_TIER_KEYS = set(_TEXT_ROUTER_TIERS) | {"image_model"}
_TIER_KEY_ALIASES = {
    "thinkingLevel": "thinking_level",
    "supportsImage": "supports_image",
    "imageOnly": "image_only",
}
_REMOTE_MEMORY_EMBEDDING_PROVIDERS = {"openai", "openai-compatible"}
_DEFAULT_REMOTE_EMBEDDING_BASE_URL = "https://api.openai.com/v1"
_DEFAULT_OLLAMA_EMBEDDING_BASE_URL = "http://localhost:11434"


@dataclass(frozen=True)
class MutationResult:
    config: GatewayConfig
    changed: bool
    restart_required: bool
    warnings: list[str] = field(default_factory=list)
    public_payload: dict[str, Any] = field(default_factory=dict)


def _clone(cfg: GatewayConfig) -> GatewayConfig:
    new_cfg = cfg.model_copy(deep=True)
    new_cfg.inherit_runtime_secrets(cfg)
    return new_cfg


def _clean_optional_str(value: str | None) -> str:
    if value is None:
        return ""
    return value.strip()


def _positive_int(value: int | str, *, label: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be an integer >= 1") from None
    if parsed < 1:
        raise ValueError(f"{label} must be >= 1")
    return parsed


def _reconcile_router_profile_for_provider(
    cfg: GatewayConfig,
    provider_id: str,
) -> None:
    current_profile = getattr(cfg.squilla_router, "tier_profile", None)
    if not getattr(cfg.squilla_router, "enabled", True):
        return
    if current_profile and str(current_profile).strip().lower() == provider_id:
        return
    if (
        not current_profile
        and provider_id == "openrouter"
        and cfg.squilla_router.tiers.get("c0", {}).get("provider") == "openrouter"
    ):
        return
    router_payload = cfg.squilla_router.model_dump(mode="python")
    router_payload.pop("tiers", None)
    if provider_id in ROUTER_TIER_PROFILE_IDS:
        router_payload["tier_profile"] = provider_id
    else:
        router_payload["enabled"] = False
        router_payload["tier_profile"] = None
    cfg.squilla_router = SquillaRouterConfig(**router_payload)


def _default_text_tier(default_tier: str | None) -> str:
    tier = normalize_text_tier(default_tier or DEFAULT_TEXT_TIER)
    return tier if tier in _TEXT_ROUTER_TIERS else DEFAULT_TEXT_TIER


def _normalize_explicit_text_tier(default_tier: str | None) -> str | None:
    if default_tier is None:
        return None
    if not str(default_tier).strip():
        return None
    tier = normalize_text_tier(default_tier)
    if not tier:
        raise ValueError("defaultTier must reference a text tier")
    if tier not in _TEXT_ROUTER_TIERS:
        raise ValueError("defaultTier must reference a text tier")
    return tier


def _router_default_model_for_provider(provider_id: str, default_tier: str | None) -> str:
    if provider_id not in ROUTER_TIER_PROFILE_IDS:
        return ""
    tiers = _router_tier_profile_defaults(provider_id)
    tier = tiers.get(_default_text_tier(default_tier)) or tiers.get("c1") or {}
    return str(tier.get("model") or "").strip()


def _normalize_tier_payload(name: str, payload: Any) -> dict[str, Any]:
    if name not in _ROUTER_TIER_KEYS:
        raise ValueError(f"unknown router tier {name!r}")
    if not isinstance(payload, dict):
        raise ValueError(f"router tier {name!r} must be an object")
    out: dict[str, Any] = {}
    for key, value in payload.items():
        out[_TIER_KEY_ALIASES.get(str(key), str(key))] = value
    return out


def _enforce_router_tier_role_invariants(name: str, tier: dict[str, Any]) -> dict[str, Any]:
    if name != "image_model":
        return tier
    out = dict(tier)
    out["supports_image"] = True
    out["image_only"] = True
    return out


def _merge_router_tiers(
    base: dict[str, Any],
    overrides: dict[str, Any] | None,
) -> dict[str, Any]:
    merged = {name: dict(value) for name, value in base.items()}
    if not overrides:
        return merged
    if not isinstance(overrides, dict):
        raise ValueError("router tiers must be an object")
    for name, raw_override in overrides.items():
        tier_name = normalize_text_tier(name) or str(name)
        override = _normalize_tier_payload(tier_name, raw_override)
        current = dict(merged.get(tier_name, {}))
        current.update(override)
        merged[tier_name] = _enforce_router_tier_role_invariants(tier_name, current)
    return merged


def _validate_router_tiers(tiers: dict[str, Any], default_tier: str) -> None:
    if default_tier not in _TEXT_ROUTER_TIERS:
        raise ValueError("defaultTier must reference a text tier")
    for tier_name in _TEXT_ROUTER_TIERS:
        tier = tiers.get(tier_name)
        if not isinstance(tier, dict):
            raise ValueError(f"router tier {tier_name!r} must be an object")
        if not str(tier.get("provider") or "").strip():
            raise ValueError(f"router tier {tier_name!r} requires provider")
        if not str(tier.get("model") or "").strip():
            raise ValueError(f"router tier {tier_name!r} requires model")


def _sync_llm_model_to_router_default(cfg: GatewayConfig) -> None:
    router = cfg.squilla_router
    if not getattr(router, "enabled", True):
        return
    default_tier = _default_text_tier(getattr(router, "default_tier", DEFAULT_TEXT_TIER))
    _validate_router_tiers(router.tiers, default_tier)
    tier = router.tiers[default_tier]
    model = str(tier.get("model") or "").strip()
    if model:
        cfg.llm.model = model


def upsert_llm_provider(
    config: GatewayConfig,
    *,
    provider_id: str,
    model: str = "",
    api_key: str = "",
    api_key_env: str = "",
    base_url: str = "",
    proxy: str = "",
    provider_routing: dict[str, str] | None = None,
) -> MutationResult:
    spec = get_provider_setup_spec(provider_id)
    if not spec.runtime_supported:
        raise ValueError(
            f"provider {provider_id!r} is not runtime-supported and cannot be configured"
        )
    model_clean = _clean_optional_str(model)
    if not model_clean:
        model_clean = _router_default_model_for_provider(
            provider_id,
            getattr(config.squilla_router, "default_tier", "c1"),
        )
    if not model_clean:
        raise ValueError("model is required")
    # When the operator omits an api_key while reconfiguring the same
    # provider that already has one stored, treat that as "leave key
    # unchanged" — matches the WebUI's "leave blank to keep current"
    # password-field affordance.
    effective_api_key = clean_header_secret(api_key, label="LLM API key")
    if api_key and api_key_env.strip():
        raise ValueError("configure either api_key or api_key_env, not both")
    effective_api_key_env = "" if api_key else api_key_env.strip()
    if not api_key and not effective_api_key_env and config.llm.provider == provider_id:
        effective_api_key_env = getattr(config.llm, "api_key_env", "").strip()
    if (
        not effective_api_key
        and spec.requires_api_key
        and not api_key_env
        and config.llm.provider == provider_id
        and config.llm.api_key
    ):
        effective_api_key = config.llm.api_key
    if spec.requires_api_key and not effective_api_key and not effective_api_key_env:
        raise ValueError(f"provider {provider_id!r} requires an api_key")
    effective_base_url = base_url or spec.default_base_url
    if spec.requires_base_url and not effective_base_url:
        raise ValueError(f"provider {provider_id!r} requires a base_url")

    new_cfg = _clone(config)
    new_cfg.llm = LlmProviderConfig(
        provider=provider_id,
        model=model_clean,
        api_key=effective_api_key,
        api_key_env=effective_api_key_env,
        base_url=effective_base_url,
        proxy=proxy,
        provider_routing=dict(provider_routing or {}),
    )
    _reconcile_router_profile_for_provider(new_cfg, provider_id)
    if api_key:
        new_cfg.clear_runtime_secret("llm.api_key")

    payload = {
        "provider": provider_id,
        "model": model_clean,
        "api_key": effective_api_key,
        "api_key_env": effective_api_key_env,
        "api_key_source": (
            "explicit" if effective_api_key else ("env" if effective_api_key_env else "none")
        ),
        "base_url": effective_base_url,
        "proxy": proxy,
        "provider_routing": dict(provider_routing or {}),
    }
    return MutationResult(
        config=new_cfg,
        changed=True,
        restart_required=False,
        warnings=[],
        public_payload=redact_provider_payload(payload),
    )


def upsert_router(
    config: GatewayConfig,
    *,
    mode: str = "recommended",
    default_tier: str | None = None,
    tiers: dict[str, Any] | None = None,
) -> MutationResult:
    if mode not in {"recommended", "openrouter-mix", "disabled"}:
        raise ValueError("router mode must be recommended, openrouter-mix, or disabled")
    router_mode = cast(RouterMode, mode)
    provider = str(config.llm.provider or "").strip().lower()
    router_payload = config.squilla_router.model_dump(mode="python")
    router_payload.pop("tiers", None)

    default_tier_override = _normalize_explicit_text_tier(default_tier)
    default_tier_clean = default_tier_override or str(
        normalize_text_tier(router_payload.get("default_tier")) or DEFAULT_TEXT_TIER
    )
    if default_tier_override is not None:
        router_payload["default_tier"] = default_tier_clean

    public_payload: dict[str, Any] = {"mode": router_mode}
    if router_mode == "disabled":
        router_payload["enabled"] = False
        router_payload["tier_profile"] = None
        public_payload.update({"enabled": False, "tier_profile": None})
    elif router_mode == "openrouter-mix":
        if provider != "openrouter":
            raise ValueError("openrouter-mix router mode is only valid for openrouter LLM provider")
        router_payload["enabled"] = True
        router_payload["tier_profile"] = None
        router_payload["tiers"] = _merge_router_tiers(
            _router_tier_profile_defaults("openrouter"),
            tiers,
        )
        public_payload.update({"enabled": True, "tier_profile": None})
    else:
        if provider not in ROUTER_TIER_PROFILE_IDS:
            router_payload["enabled"] = False
            router_payload["tier_profile"] = None
            public_payload.update({"enabled": False, "tier_profile": None})
        else:
            router_payload["enabled"] = True
            router_payload["tier_profile"] = provider
            router_payload["tiers"] = _merge_router_tiers(
                _router_tier_profile_defaults(provider),
                tiers,
            )
            public_payload.update({"enabled": True, "tier_profile": provider})
    if router_payload.get("enabled"):
        _validate_router_tiers(
            cast(dict[str, Any], router_payload.get("tiers") or {}),
            default_tier_clean,
        )

    new_cfg = _clone(config)
    new_cfg.squilla_router = SquillaRouterConfig(**router_payload)
    _sync_llm_model_to_router_default(new_cfg)
    public_payload["default_tier"] = new_cfg.squilla_router.default_tier
    public_payload["tiers"] = new_cfg.squilla_router.tiers
    return MutationResult(
        config=new_cfg,
        changed=True,
        restart_required=False,
        warnings=[],
        public_payload=public_payload,
    )


def upsert_search_provider(
    config: GatewayConfig,
    *,
    provider_id: str,
    api_key: str = "",
    api_key_env: str = "",
    max_results: int | str = 5,
    proxy: str = "",
    use_env_proxy: bool = False,
    fallback_policy: str = "off",
    diagnostics: bool = False,
) -> MutationResult:
    spec = get_search_provider_setup_spec(provider_id)
    if not spec.runtime_supported:
        raise ValueError(
            f"search provider {provider_id!r} is not runtime-supported and cannot be configured"
        )
    effective_max_results = _positive_int(max_results, label="max_results")
    if fallback_policy not in {"off", "network"}:
        raise ValueError("fallback_policy must be 'off' or 'network'")
    fallback_policy_value = cast(SearchFallbackPolicy, fallback_policy)

    effective_api_key = (
        clean_header_secret(api_key, label="Search API key")
        if spec.requires_api_key
        else ""
    )
    effective_api_key_env = (
        ""
        if api_key or not spec.requires_api_key
        else api_key_env.strip()
    )
    if (
        not effective_api_key
        and not effective_api_key_env
        and spec.requires_api_key
        and config.search_provider == provider_id
        and config.search_api_key
    ):
        effective_api_key = config.search_api_key
    if spec.requires_api_key and not effective_api_key and not effective_api_key_env:
        raise ValueError(f"search provider {provider_id!r} requires an api_key")

    new_cfg = _clone(config)
    new_cfg.search_provider = provider_id
    new_cfg.search_api_key = effective_api_key
    new_cfg.search_api_key_env = effective_api_key_env
    new_cfg.search_max_results = effective_max_results
    new_cfg.search_proxy = proxy
    new_cfg.search_use_env_proxy = bool(use_env_proxy)
    new_cfg.search_fallback_policy = fallback_policy_value
    new_cfg.search_diagnostics = bool(diagnostics)
    if api_key:
        new_cfg.clear_runtime_secret("search_api_key")

    api_key_source = (
        "explicit" if effective_api_key else ("env" if effective_api_key_env else "none")
    )
    payload = {
        "provider": provider_id,
        "api_key": effective_api_key,
        "api_key_env": effective_api_key_env,
        "api_key_source": api_key_source,
        "max_results": effective_max_results,
        "proxy": proxy,
        "use_env_proxy": bool(use_env_proxy),
        "fallback_policy": fallback_policy_value,
        "diagnostics": bool(diagnostics),
    }
    return MutationResult(
        config=new_cfg,
        changed=True,
        restart_required=False,
        warnings=[],
        public_payload=redact_search_payload(payload),
    )


def _image_generation_provider_config(config: GatewayConfig, provider_id: str) -> Any:
    providers = config.image_generation.providers
    provider_config = getattr(providers, provider_id, None)
    if provider_config is None:
        raise KeyError(f"unknown image generation provider: {provider_id!r}")
    return provider_config


def _image_generation_api_key_source(
    config: GatewayConfig,
    *,
    provider_id: str,
    api_key: str,
    env_key: str,
) -> str:
    if api_key:
        return "explicit"
    if env_key and os.environ.get(env_key):
        return "env"
    if config.llm.provider == provider_id and config.llm.api_key:
        return "llm_fallback"
    return "none"


def upsert_image_generation_provider(
    config: GatewayConfig,
    *,
    provider_id: str,
    primary: str = "",
    api_key: str = "",
    api_key_env: str = "",
    base_url: str = "",
    enabled: bool = True,
) -> MutationResult:
    spec = get_image_generation_provider_setup_spec(provider_id)
    if not spec.runtime_supported:
        raise ValueError(
            f"image generation provider {provider_id!r} is not runtime-supported "
            "and cannot be configured"
        )
    primary_model = primary or spec.default_model
    primary_provider, sep, _model = primary_model.partition("/")
    if not sep or primary_provider != provider_id:
        raise ValueError(
            "primary must be a provider/model reference for "
            f"image generation provider {provider_id!r}"
    )

    current_provider_cfg = _image_generation_provider_config(config, provider_id)
    explicit_env_key = _clean_optional_str(api_key_env)
    if api_key and explicit_env_key:
        raise ValueError("configure either api_key or api_key_env, not both")
    effective_api_key = clean_header_secret(
        api_key or getattr(current_provider_cfg, "api_key", ""),
        label="Image API key",
    )
    current_env_key = getattr(current_provider_cfg, "api_key_env", spec.env_key) or ""
    if api_key:
        env_key = ""
    else:
        env_key = explicit_env_key or current_env_key or spec.env_key
    has_saved_env_reference = bool(
        explicit_env_key or (current_env_key and current_env_key != spec.env_key)
    )
    api_key_source = _image_generation_api_key_source(
        config,
        provider_id=provider_id,
        api_key=effective_api_key,
        env_key=env_key,
    )
    if (
        enabled
        and spec.requires_api_key
        and api_key_source == "none"
        and not has_saved_env_reference
    ):
        raise ValueError(
            f"image generation provider {provider_id!r} requires an api_key, "
            f"{spec.env_key}, or a matching configured LLM provider"
        )
    if api_key_source == "none" and has_saved_env_reference:
        api_key_source = "missing_env"

    effective_base_url = (
        base_url or getattr(current_provider_cfg, "base_url", "") or spec.default_base_url
    )

    new_cfg = _clone(config)
    new_cfg.image_generation.enabled = bool(enabled)
    new_cfg.image_generation.primary = primary_model
    next_provider_cfg = _image_generation_provider_config(new_cfg, provider_id)
    next_provider_cfg.api_key = effective_api_key
    next_provider_cfg.api_key_env = env_key
    next_provider_cfg.base_url = effective_base_url
    if api_key:
        new_cfg.clear_runtime_secret(f"image_generation.providers.{provider_id}.api_key")

    payload = {
        "provider": provider_id,
        "enabled": bool(enabled),
        "primary": primary_model,
        "api_key": effective_api_key,
        "api_key_env": env_key,
        "api_key_source": api_key_source,
        "base_url": effective_base_url,
    }
    return MutationResult(
        config=new_cfg,
        changed=True,
        restart_required=False,
        warnings=[],
        public_payload=redact_image_generation_payload(payload),
    )


def disable_image_generation(config: GatewayConfig) -> MutationResult:
    new_cfg = _clone(config)
    new_cfg.image_generation.enabled = False
    return MutationResult(
        config=new_cfg,
        changed=True,
        restart_required=False,
        warnings=[],
        public_payload={
            "enabled": False,
            "primary": new_cfg.image_generation.primary,
        },
    )


def _audio_provider_config(config: GatewayConfig, provider_id: str) -> Any:
    providers = config.audio.providers
    provider_config = getattr(providers, provider_id, None)
    if provider_config is None:
        raise KeyError(f"unknown audio provider: {provider_id!r}")
    return provider_config


def _audio_api_key_source(*, api_key: str, env_key: str) -> str:
    if api_key:
        return "explicit"
    if env_key and os.environ.get(env_key):
        return "env"
    if env_key:
        return "missing_env"
    return "none"


def upsert_audio_provider(
    config: GatewayConfig,
    *,
    provider_id: str,
    api_key: str = "",
    api_key_env: str = "",
    base_url: str = "",
    enabled: bool = True,
    tts_voice: str = "",
    tts_model: str = "",
    language_code: str = "",
) -> MutationResult:
    spec = get_audio_provider_setup_spec(provider_id)
    if not spec.runtime_supported:
        raise ValueError(
            f"audio provider {provider_id!r} is not runtime-supported and cannot be configured"
        )
    if provider_id != "elevenlabs":
        raise ValueError(f"audio provider {provider_id!r} is not supported")

    current_provider_cfg = _audio_provider_config(config, provider_id)
    explicit_env_key = _clean_optional_str(api_key_env)
    if api_key and explicit_env_key:
        raise ValueError("configure either api_key or api_key_env, not both")
    effective_api_key = clean_header_secret(
        api_key or getattr(current_provider_cfg, "api_key", ""),
        label="Audio API key",
    )
    current_env_key = getattr(current_provider_cfg, "api_key_env", spec.env_key) or ""
    env_key = "" if api_key else (explicit_env_key or current_env_key or spec.env_key)
    api_key_source = _audio_api_key_source(
        api_key=effective_api_key,
        env_key=env_key,
    )
    if enabled and spec.requires_api_key and api_key_source == "none":
        raise ValueError(
            f"audio provider {provider_id!r} requires an api_key or {spec.env_key}"
        )

    effective_base_url = (
        base_url or getattr(current_provider_cfg, "base_url", "") or spec.default_base_url
    )
    effective_tts_voice = tts_voice or config.audio.tts.voice or spec.default_tts_voice
    effective_tts_model = tts_model or config.audio.tts.model or spec.default_tts_model
    effective_language_code = language_code or config.audio.tts.language_code

    new_cfg = _clone(config)
    new_cfg.audio.enabled = bool(enabled)
    next_provider_cfg = _audio_provider_config(new_cfg, provider_id)
    next_provider_cfg.api_key = effective_api_key
    next_provider_cfg.api_key_env = env_key
    next_provider_cfg.base_url = effective_base_url
    new_cfg.audio.tts.voice = effective_tts_voice
    new_cfg.audio.tts.model = effective_tts_model
    new_cfg.audio.tts.language_code = effective_language_code
    if api_key:
        new_cfg.clear_runtime_secret(f"audio.providers.{provider_id}.api_key")

    payload = {
        "provider": provider_id,
        "enabled": bool(enabled),
        "api_key": effective_api_key,
        "api_key_env": env_key,
        "api_key_source": api_key_source,
        "base_url": effective_base_url,
        "tts_voice": effective_tts_voice,
        "tts_model": effective_tts_model,
        "language_code": effective_language_code,
    }
    return MutationResult(
        config=new_cfg,
        changed=True,
        restart_required=False,
        warnings=[],
        public_payload=redact_audio_payload(payload),
    )


def upsert_memory_embedding(
    config: GatewayConfig,
    *,
    provider: str,
    model: str | None = None,
    api_key: str | None = None,
    api_key_env: str | None = None,
    base_url: str | None = None,
    onnx_dir: str | None = None,
) -> MutationResult:
    if provider not in {"auto", "none", "local", "openai", "openai-compatible", "ollama"}:
        raise ValueError(f"unknown memory embedding provider: {provider!r}")

    new_cfg = _clone(config)
    old_memory = config.memory.model_dump(mode="python")
    current = config.memory.embedding
    model_value = _clean_optional_str(model)
    api_key_value = _clean_optional_str(api_key)
    api_key_env_value = _clean_optional_str(api_key_env)
    if api_key_value and api_key_env_value:
        raise ValueError("configure either api_key or api_key_env, not both")
    base_url_value = _clean_optional_str(base_url)
    onnx_dir_value = _clean_optional_str(onnx_dir)
    payload: dict[str, Any] = {"provider": provider}

    if provider in _REMOTE_MEMORY_EMBEDDING_PROVIDERS:
        current_api_key_env = _clean_optional_str(
            getattr(current.remote, "api_key_env", None)
        )
        effective_api_key_env = "" if api_key_value else (
            api_key_env_value or current_api_key_env or ""
        )
        effective_api_key = (
            api_key_value
            or ("" if effective_api_key_env else current.remote.api_key or current.api_key or "")
        )
        if not effective_api_key and not effective_api_key_env:
            raise ValueError(
                "remote memory embedding provider requires an api_key or api_key_env"
            )
        payload["remote"] = {
            "base_url": (
                base_url_value
                or current.remote.base_url
                or current.base_url
                or _DEFAULT_REMOTE_EMBEDDING_BASE_URL
            ),
        }
        if effective_api_key:
            payload["remote"]["api_key"] = effective_api_key
        if effective_api_key_env:
            payload["remote"]["api_key_env"] = effective_api_key_env
        remote_model = model_value or current.remote.model or current.model
        if remote_model:
            payload["remote"]["model"] = remote_model
    elif provider == "auto":
        remote_payload: dict[str, str] = {}
        current_api_key_env = _clean_optional_str(
            getattr(current.remote, "api_key_env", None)
        )
        effective_api_key_env = "" if api_key_value else (
            api_key_env_value or current_api_key_env or ""
        )
        effective_api_key = (
            api_key_value
            or ("" if effective_api_key_env else current.remote.api_key or current.api_key or "")
        )
        if effective_api_key:
            remote_payload["api_key"] = effective_api_key
        if effective_api_key_env:
            remote_payload["api_key_env"] = effective_api_key_env
        remote_base_url = base_url_value or current.remote.base_url or current.base_url
        if remote_base_url:
            remote_payload["base_url"] = remote_base_url
        remote_model = model_value or current.remote.model or (
            current.model if (effective_api_key or effective_api_key_env) else None
        )
        if remote_model:
            remote_payload["model"] = remote_model
        if remote_payload:
            payload["remote"] = remote_payload
    elif provider == "local":
        payload["local"] = {}
        local_onnx_dir = onnx_dir_value or (
            current.local.onnx_dir if current.requested_provider == "local" else ""
        )
        if local_onnx_dir:
            payload["local"]["onnx_dir"] = local_onnx_dir
    elif provider == "ollama":
        payload["ollama"] = {
            "base_url": (
                base_url_value
                or current.ollama.base_url
                or _DEFAULT_OLLAMA_EMBEDDING_BASE_URL
            ),
        }
        ollama_model = model_value or current.ollama.model
        if ollama_model:
            payload["ollama"]["model"] = ollama_model

    new_cfg.memory.embedding = MemoryEmbeddingConfig.model_validate(payload)
    changed = old_memory != new_cfg.memory.model_dump(mode="python")
    if api_key_value or api_key_env_value:
        new_cfg.clear_runtime_secret("memory.embedding.remote.api_key")
        new_cfg.clear_runtime_secret("memory.embedding.api_key")

    return MutationResult(
        config=new_cfg,
        changed=changed,
        restart_required=changed,
        warnings=[],
        public_payload=redact_memory_embedding_payload(payload),
    )


def _channel_entries_as_dicts(cfg: GatewayConfig) -> list[dict[str, Any]]:
    return [e.model_dump(mode="python") for e in cfg.channels.channels]


def list_channel_entries(config: GatewayConfig) -> list[dict[str, Any]]:
    return [redact_channel_entry(d.get("type", ""), d) for d in _channel_entries_as_dicts(config)]


def validate_channel_entry(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise TypeError("channel entry payload must be a dict")
    type_name = payload.get("type")
    if not isinstance(type_name, str) or not type_name:
        raise ValueError("channel entry requires non-empty 'type'")
    if type_name not in discover_all():
        raise ValueError(f"unknown channel type: {type_name!r}")
    full = {"agent_id": "main", "enabled": True, **payload}
    try:
        entry = parse_channel_entry(full)
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc
    if (
        type_name == "slack"
        and getattr(entry, "connection_mode", "webhook") == "webhook"
        and not str(getattr(entry, "signing_secret", "") or "").strip()
    ):
        raise ValueError("slack webhook channels require signing_secret")
    return entry.model_dump(mode="python")


def upsert_channel(
    config: GatewayConfig,
    *,
    entry_payload: dict[str, Any],
) -> MutationResult:
    merged = _merge_with_existing_secrets(config, entry_payload)
    normalized = validate_channel_entry(merged)
    name = normalized["name"]
    new_cfg = _clone(config)
    raw = _channel_entries_as_dicts(new_cfg)
    replaced = False
    for idx, existing in enumerate(raw):
        if existing.get("name") == name:
            raw[idx] = normalized
            replaced = True
            break
    if not replaced:
        raw.append(normalized)
    new_cfg.channels = ChannelsConfig.model_validate({"channels": raw})

    return MutationResult(
        config=new_cfg,
        changed=True,
        restart_required=True,
        warnings=[],
        public_payload=redact_channel_entry(normalized["type"], normalized),
    )


def _merge_with_existing_secrets(
    config: GatewayConfig, payload: dict[str, Any]
) -> dict[str, Any]:
    """Mirror upsert_llm_provider: blank secret in payload = keep current.

    Only secret fields are auto-preserved here so that re-adding an entry
    by name does not require re-typing credentials. Non-secret partial
    updates belong to the edit path, which seeds the full existing entry
    in the CLI before calling upsert.
    """
    from opensquilla.onboarding.channel_specs import get_channel_setup_spec

    type_name = payload.get("type")
    name = payload.get("name")
    if not isinstance(type_name, str) or not isinstance(name, str):
        return dict(payload)
    try:
        spec = get_channel_setup_spec(type_name)
    except KeyError:
        return dict(payload)
    existing = next(
        (
            e.model_dump(mode="python")
            for e in config.channels.channels
            if e.name == name and e.type == type_name
        ),
        None,
    )
    if existing is None:
        return dict(payload)
    merged = dict(payload)
    for f in spec.fields:
        if not f.secret:
            continue
        if merged.get(f.name) in ("", None) and existing.get(f.name):
            merged[f.name] = existing[f.name]
    return merged


def remove_channel(
    config: GatewayConfig,
    *,
    name: str,
) -> MutationResult:
    new_cfg = _clone(config)
    raw = _channel_entries_as_dicts(new_cfg)
    remaining = [e for e in raw if e.get("name") != name]
    if len(remaining) == len(raw):
        raise KeyError(f"no channel named {name!r}")
    new_cfg.channels = ChannelsConfig.model_validate({"channels": remaining})
    return MutationResult(
        config=new_cfg,
        changed=True,
        restart_required=True,
        public_payload={"name": name, "removed": True},
    )


def set_channel_enabled(
    config: GatewayConfig,
    *,
    name: str,
    enabled: bool,
) -> MutationResult:
    new_cfg = _clone(config)
    raw = _channel_entries_as_dicts(new_cfg)
    found = False
    for entry in raw:
        if entry.get("name") == name:
            entry["enabled"] = bool(enabled)
            found = True
            break
    if not found:
        raise KeyError(f"no channel named {name!r}")
    new_cfg.channels = ChannelsConfig.model_validate({"channels": raw})
    return MutationResult(
        config=new_cfg,
        changed=True,
        restart_required=True,
        public_payload={"name": name, "enabled": bool(enabled)},
    )
