"""Mutations for provider/channel onboarding configuration."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, cast, get_args

from pydantic import ValidationError

from opensquilla.channels.registry import discover_all, parse_channel_entry
from opensquilla.gateway.config import (
    ChannelsConfig,
    GatewayConfig,
    LlmEnsembleConfig,
    LlmProviderConfig,
    MemoryEmbeddingConfig,
    SquillaRouterConfig,
    _default_tiers,
)
from opensquilla.gateway.config_secrets import (
    clear_runtime_secret_paths,
    inherit_runtime_secrets,
)
from opensquilla.onboarding.audio_specs import get_audio_provider_setup_spec
from opensquilla.onboarding.endpoint_identity import base_url_allows_credential_reuse
from opensquilla.onboarding.image_generation_specs import (
    get_image_generation_provider_setup_spec,
)
from opensquilla.onboarding.provider_specs import get_provider_setup_spec
from opensquilla.onboarding.redaction import (
    redact_audio_payload,
    redact_channel_entry,
    redact_error_text,
    redact_image_generation_payload,
    redact_memory_embedding_payload,
    redact_provider_payload,
    redact_router_tiers_payload,
    redact_search_payload,
)
from opensquilla.onboarding.search_specs import get_search_provider_setup_spec
from opensquilla.provider.preset_registry import ProviderPreset, get_preset
from opensquilla.router_tiers import (
    DEFAULT_TEXT_TIER,
    TEXT_TIERS,
    normalize_text_tier,
)
from opensquilla.search.types import MAX_SEARCH_RESULTS
from opensquilla.secrets import clean_header_secret

SearchFallbackPolicy = Literal["off", "network"]
RouterMode = Literal["recommended", "openrouter-mix", "custom", "disabled"]
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
    inherit_runtime_secrets(cfg, new_cfg)
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


def _preset_tiers_with_model(preset: ProviderPreset, model: str) -> dict[str, dict]:
    tiers = preset.tier_defaults()
    for tier in tiers.values():
        if not str(tier.get("model") or "").strip():
            tier["model"] = model
    return tiers


def _reconcile_router_profile_for_provider(
    cfg: GatewayConfig,
    provider_id: str,
) -> None:
    router_enabled = bool(getattr(cfg.squilla_router, "enabled", True))
    preset = get_preset(provider_id)
    router_payload = cfg.squilla_router.model_dump(mode="python")
    router_payload.pop("tiers", None)
    router_payload["enabled"] = router_enabled
    if preset is None:
        router_payload["enabled"] = False
        router_payload["tier_profile"] = None
    elif preset.persistable and router_enabled:
        router_payload["tier_profile"] = provider_id
    else:
        router_payload["tier_profile"] = None
        router_payload["tiers"] = _preset_tiers_with_model(
            preset,
            str(getattr(cfg.llm, "model", "") or "").strip(),
        )
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
    preset = get_preset(provider_id)
    if preset is None or preset.synthesized:
        return ""
    tiers = preset.tier_defaults()
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


def _canonical_tier_value(tier: Mapping[str, Any]) -> dict[str, Any]:
    thinking = tier.get("thinking_level")
    if thinking is None:
        thinking = tier.get("thinkingLevel")
    return {
        "provider": str(tier.get("provider") or "").strip().lower(),
        "model": str(tier.get("model") or "").strip(),
        "description": str(tier.get("description") or "").strip(),
        "thinking_level": (str(thinking or "").strip() or None),
        "supports_image": bool(tier.get("supports_image", tier.get("supportsImage", False))),
        "image_only": bool(tier.get("image_only", tier.get("imageOnly", False))),
    }


def _canonical_tier_map(tiers: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    normalized: dict[str, dict[str, Any]] = {}
    if not isinstance(tiers, Mapping):
        return normalized
    for raw_name, raw_tier in tiers.items():
        name = normalize_text_tier(raw_name) or str(raw_name)
        if name not in _ROUTER_TIER_KEYS or not isinstance(raw_tier, Mapping):
            continue
        tier = _normalize_tier_payload(name, raw_tier)
        tier = _enforce_router_tier_role_invariants(name, tier)
        normalized[name] = _canonical_tier_value(tier)
    return normalized


def _tiers_equal_after_canonical_normalization(
    candidate: Mapping[str, Any] | None,
    preset_tiers: Mapping[str, Any],
) -> bool:
    return _canonical_tier_map(candidate) == _canonical_tier_map(preset_tiers)


def _router_tiers_hand_customized(config: GatewayConfig, *, explicit_model: str = "") -> bool:
    """True when squilla_router carries an inline, hand-edited tier ladder.

    A set ``tier_profile`` means the ladder is profile-derived (reconciling
    rewrites the same compact form, which is not destructive). Inline tiers
    that canonically equal the model default or the active provider's preset
    seeded with a machine-known model are reconcile-refreshable states a
    previous save produced — only anything else is an operator-authored
    ladder that a same-provider re-save must not overwrite.

    The seeded comparison runs against several candidate models, not just
    the currently stored ``llm.model``: after an out-of-band ``llm.model``
    change (config.set RPC, TOML hand-edit) the stored ladder still carries
    the model of the save that seeded it, so testing the save's explicit
    model and each model the ladder itself names keeps machine-seeded
    ladders recognizable — otherwise a re-save naming the new model would
    skip reconciliation and leave every tier pinned to the old model.
    """
    router = config.squilla_router
    if getattr(router, "tier_profile", None):
        return False
    tiers = getattr(router, "tiers", {}) or {}
    if not tiers:
        return False
    if _tiers_equal_after_canonical_normalization(tiers, _default_tiers()):
        return False
    provider = str(getattr(config.llm, "provider", "") or "").strip().lower()
    preset = get_preset(provider)
    if preset is not None:
        candidate_models = {
            str(getattr(config.llm, "model", "") or "").strip(),
            str(explicit_model or "").strip(),
        }
        for tier in tiers.values():
            if isinstance(tier, Mapping):
                candidate_models.add(str(tier.get("model") or "").strip())
        for candidate in sorted(candidate_models):
            seeded = _preset_tiers_with_model(preset, candidate)
            if _tiers_equal_after_canonical_normalization(tiers, seeded):
                return False
    return True


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


def _tier_provider_credentials_resolvable(
    provider_id: str,
    llm_profiles: dict[str, Any] | None,
) -> bool:
    from opensquilla.provider.registry import UnknownProviderError, get_provider_spec

    try:
        spec = get_provider_spec(provider_id)
    except UnknownProviderError:
        return False
    if not spec.runtime_supported:
        return False
    profile = (llm_profiles or {}).get(provider_id)
    if str(getattr(profile, "api_key", "") or "").strip():
        return True
    if not spec.requires_api_key():
        return True
    # A rotation pool resolves when any of its named env vars is set —
    # mirror the runtime path so pool-only profiles are not flagged as
    # credential-less.
    for pool_env_name in getattr(profile, "api_key_env_pool", None) or []:
        pool_env_name = str(pool_env_name or "").strip()
        if pool_env_name and pool_env_name != "OAuth" and os.environ.get(pool_env_name):
            return True
    env_name = str(getattr(profile, "api_key_env", "") or "").strip() or spec.env_key
    return bool(env_name and env_name != "OAuth" and os.environ.get(env_name))


def _cross_provider_tier_warnings(
    tiers: dict[str, Any],
    active_provider: str,
    *,
    cross_provider_enabled: bool = False,
    llm_profiles: dict[str, Any] | None = None,
) -> list[str]:
    """Warn about tiers naming a provider other than the active LLM provider.

    Flag off: such a tier's model id is silently requested from the active
    provider with the active credentials — warn about the misroute. Flag on:
    the tier executes on its own provider, so the check flips to credential
    resolvability (profile or env; secrets are never guessed).
    """
    if not active_provider:
        return []
    warnings: list[str] = []
    for tier_name in sorted(tiers):
        tier = tiers.get(tier_name)
        if not isinstance(tier, dict):
            continue
        tier_provider = str(tier.get("provider") or "").strip().lower()
        if not tier_provider or tier_provider == active_provider:
            continue
        if not cross_provider_enabled:
            warnings.append(
                f"Router tier '{tier_name}' names provider '{tier_provider}', but the "
                f"active LLM provider is '{active_provider}'. Cross-provider routing is "
                f"not enabled (squilla_router.cross_provider_tiers), so this tier's "
                f"model will be requested from '{active_provider}'."
            )
        elif not _tier_provider_credentials_resolvable(tier_provider, llm_profiles):
            warnings.append(
                f"Router tier '{tier_name}' routes to provider '{tier_provider}' but no "
                f"credentials resolve for it. Add [llm_profiles.{tier_provider}] with "
                f"api_key or api_key_env, or export the provider's default env key; "
                f"until then the tier falls back to '{active_provider}'."
            )
    return warnings


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


def _resolve_provider_preset(preset_id: str, provider_id: str) -> ProviderPreset | None:
    """Validate an explicitly requested preset against the target provider.

    Returns ``None`` when no preset was requested. A preset id that does not
    exist or that belongs to a different provider is a validation error —
    presets are provider-bound (packaged legacy ids and synthesized ids both
    equal their provider id).
    """
    preset_id_clean = _clean_optional_str(preset_id).lower()
    if not preset_id_clean:
        return None
    preset = get_preset(preset_id_clean)
    if preset is None or preset.provider_id != provider_id:
        raise ValueError(
            f"preset {preset_id!r} does not apply to provider {provider_id!r}"
        )
    return preset


def _apply_provider_preset(cfg: GatewayConfig, preset: ProviderPreset, model: str) -> None:
    """Apply an explicitly requested registry preset to the router config.

    D18: this runs ONLY for an explicit ``presetId`` — a plain provider save
    goes through ``_reconcile_router_profile_for_provider`` unchanged, so save
    paths stay pinned to the legacy nine unless the user asked for a preset.

    Persistable (legacy-nine) preset → exactly today's recommended write
    shape: ``enabled=True`` with the persisted ``tier_profile`` id and no
    inline tiers, so ``to_toml_dict`` keeps persisting the compact profile
    form.

    Curated-inline or synthesized preset → the custom-mode write shape:
    ``enabled=True``, ``tier_profile=None`` (non-legacy ids must never
    persist — downgrade contract) plus the preset's expanded tiers. A
    synthesized preset carries no curated model ladder (its ``default_model``
    may be empty), so empty tier model slots are completed with this save's
    effective model — the operator's explicit model is the only model binding
    this save knows; a curated-inline ladder is already fully bound.
    """
    router_payload = cfg.squilla_router.model_dump(mode="python")
    router_payload.pop("tiers", None)
    router_payload["enabled"] = True
    if preset.persistable:
        router_payload["tier_profile"] = preset.preset_id
    else:
        router_payload["tier_profile"] = None
        router_payload["tiers"] = _preset_tiers_with_model(preset, model)
    cfg.squilla_router = SquillaRouterConfig(**router_payload)


def upsert_llm_provider(
    config: GatewayConfig,
    *,
    provider_id: str,
    model: str | None = None,
    api_key: str | None = None,
    api_key_env: str | None = None,
    preserve_api_key: bool = False,
    base_url: str | None = None,
    proxy: str | None = None,
    provider_routing: dict[str, str] | None = None,
    preset_id: str | None = None,
) -> MutationResult:
    """Save the active LLM provider configuration.

    Keep-current contract (``None`` = "not passed"): when re-saving the
    provider that is already active (``config.llm.provider == provider_id``,
    e.g. a key rotation), every optional field left at ``None`` keeps its
    stored value — ``model``, ``base_url``, ``proxy``, ``provider_routing``,
    plus parameterless fields such as ``max_tokens`` and ``thinking``, which
    are always carried over verbatim on a same-provider re-save. Explicit
    values always win, and an explicit empty string keeps its legacy
    meaning: ``model=""``/``base_url=""`` fall back to derived defaults
    (preset/tier model, spec base URL), ``proxy=""`` clears the proxy, and
    optional-provider ``api_key=""`` clears the stored key unless the caller
    explicitly sets ``preserve_api_key=True``. Required providers retain the
    established blank-means-keep behavior. On a provider switch nothing is
    carried over except the caller's values; optional credentials never
    follow ``preserve_api_key`` across providers or endpoint origins.

    A same-provider re-save also never overwrites an operator-authored
    inline router ladder: the router profile is reconciled only when the
    provider id actually changes or when the current router state is one a
    previous save produced (compact ``tier_profile`` form, the packaged
    default, or the provider preset seeded with the stored model).
    """
    spec = get_provider_setup_spec(provider_id)
    if not spec.runtime_supported:
        raise ValueError(
            f"provider {provider_id!r} is not runtime-supported and cannot be configured"
        )
    api_key = api_key or ""
    api_key_env = api_key_env or ""
    preset = _resolve_provider_preset(preset_id or "", provider_id)
    same_provider = config.llm.provider == provider_id
    model_clean = _clean_optional_str(model)
    if not model_clean and model is None and same_provider:
        # Not passed at all: keep the stored model on a same-provider
        # re-save instead of resetting it to a derived default.
        model_clean = str(config.llm.model or "").strip()
    if not model_clean and preset is not None:
        # Explicit preset application: the preset's default model fills the
        # provider's direct model when the caller gave none.
        model_clean = preset.default_model.strip()
    if not model_clean:
        model_clean = _router_default_model_for_provider(
            provider_id,
            getattr(config.squilla_router, "default_tier", "c1"),
        )
    if not model_clean:
        raise ValueError("model is required")
    effective_base_url = base_url or ""
    if not effective_base_url and base_url is None and same_provider:
        effective_base_url = str(config.llm.base_url or "")
    if not effective_base_url:
        effective_base_url = spec.default_base_url
    stored_credentials_match_endpoint = base_url_allows_credential_reuse(
        config.llm.base_url,
        effective_base_url,
    )
    # Required providers retain their established blank-means-keep behavior.
    # Optional providers preserve a stored explicit key only when the caller
    # opts in and the final endpoint remains same-origin. This keeps legacy
    # api_key="" clearing intact for existing RPC clients while giving newer
    # clients an unambiguous password-field "leave current key unchanged"
    # affordance without carrying secrets to another configurable endpoint.
    effective_api_key = clean_header_secret(api_key, label="LLM API key")
    if api_key and api_key_env.strip():
        raise ValueError("configure either api_key or api_key_env, not both")
    effective_api_key_env = "" if api_key else api_key_env.strip()
    if (
        not api_key
        and not effective_api_key_env
        and same_provider
        and (
            spec.requires_api_key
            or (spec.accepts_api_key and stored_credentials_match_endpoint)
        )
    ):
        effective_api_key_env = getattr(config.llm, "api_key_env", "").strip()
    stored_api_key_is_explicit = bool(config.llm.api_key) and (
        "llm.api_key" not in getattr(config, "_runtime_secret_paths", set())
    )
    preserve_optional_api_key = (
        preserve_api_key
        and spec.accepts_api_key
        and stored_api_key_is_explicit
        and stored_credentials_match_endpoint
    )
    if (
        not effective_api_key
        and not api_key_env.strip()
        and same_provider
        and config.llm.api_key
        and (spec.requires_api_key or preserve_optional_api_key)
    ):
        effective_api_key = config.llm.api_key
    if spec.requires_api_key and not effective_api_key and not effective_api_key_env:
        raise ValueError(f"provider {provider_id!r} requires an api_key")
    if spec.requires_base_url and not effective_base_url:
        raise ValueError(f"provider {provider_id!r} requires a base_url")
    if proxy is None:
        effective_proxy = str(config.llm.proxy or "") if same_provider else ""
    else:
        effective_proxy = proxy
    if provider_routing is None:
        effective_provider_routing = (
            dict(config.llm.provider_routing or {}) if same_provider else {}
        )
    else:
        effective_provider_routing = dict(provider_routing)

    new_cfg = _clone(config)
    # Seed from the stored section on a same-provider re-save so fields
    # without a parameter here (max_tokens, thinking, future additions) keep
    # their values instead of silently resetting to model defaults.
    llm_payload: dict[str, Any] = (
        config.llm.model_dump(mode="python") if same_provider else {}
    )
    llm_payload.update(
        {
            "provider": provider_id,
            "model": model_clean,
            "api_key": effective_api_key,
            "api_key_env": effective_api_key_env,
            "base_url": effective_base_url,
            "proxy": effective_proxy,
            "provider_routing": effective_provider_routing,
        }
    )
    new_cfg.llm = LlmProviderConfig(**llm_payload)
    if preset is not None:
        # Explicit user action only — a plain save (no presetId) must keep
        # today's reconcile behavior byte-for-byte (D18).
        _apply_provider_preset(new_cfg, preset, model_clean)
    elif same_provider and _router_tiers_hand_customized(
        config, explicit_model=model_clean
    ):
        # Same-provider re-save over a hand-edited inline ladder: the router
        # state already belongs to this provider, and reconciling would only
        # replace the operator's tiers with the packaged profile. Leave it.
        pass
    else:
        _reconcile_router_profile_for_provider(new_cfg, provider_id)
    if api_key:
        clear_runtime_secret_paths(new_cfg, {"llm.api_key"})
    # Explicit endpoint/proxy values override any boot-time env resolution:
    # drop the runtime-override record so the persist layer writes exactly
    # what the operator passed even when it equals the env value. Only a
    # genuinely explicit NON-EMPTY value counts: ``None`` is keep-current and
    # the empty string is the legacy RPC reset sentinel ("derive default"),
    # so neither names an operator endpoint — clearing the record for them
    # would let a boot-time env value get baked into config.toml by a plain
    # re-save (e.g. a WebUI key rotation that sends baseUrl="").
    if base_url:
        new_cfg.clear_runtime_override("llm.base_url")
    if proxy:
        new_cfg.clear_runtime_override("llm.proxy")

    payload = {
        "provider": provider_id,
        "model": model_clean,
        "api_key": effective_api_key,
        "api_key_env": effective_api_key_env,
        "api_key_source": (
            "explicit" if effective_api_key else ("env" if effective_api_key_env else "none")
        ),
        "base_url": effective_base_url,
        "proxy": effective_proxy,
        "provider_routing": effective_provider_routing,
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
    cross_provider_tiers: bool | None = None,
    tier_provider_mismatch: str | None = None,
) -> MutationResult:
    if mode not in {"recommended", "openrouter-mix", "custom", "disabled"}:
        raise ValueError(
            "router mode must be recommended, openrouter-mix, custom, or disabled"
        )
    router_mode = cast(RouterMode, mode)
    provider = str(config.llm.provider or "").strip().lower()
    router_payload = config.squilla_router.model_dump(mode="python")
    router_payload.pop("tiers", None)
    if cross_provider_tiers is not None:
        router_payload["cross_provider_tiers"] = bool(cross_provider_tiers)
    if tier_provider_mismatch is not None:
        mismatch_policy = str(tier_provider_mismatch or "").strip()
        if mismatch_policy not in {"route", "veto"}:
            raise ValueError("tierProviderMismatch must be route or veto")
        router_payload["tier_provider_mismatch"] = mismatch_policy

    default_tier_override = _normalize_explicit_text_tier(default_tier)
    default_tier_clean = default_tier_override or str(
        normalize_text_tier(router_payload.get("default_tier")) or DEFAULT_TEXT_TIER
    )
    if default_tier_override is not None:
        router_payload["default_tier"] = default_tier_clean

    public_payload: dict[str, Any] = {}
    if router_mode == "disabled":
        router_payload["enabled"] = False
        router_payload["tier_profile"] = None
        # Keep the effective ladder stored inline while disabled so a later
        # re-enable can restore an operator-authored tier ladder instead of
        # silently resetting it to the packaged defaults.
        router_payload["tiers"] = {
            name: (dict(tier) if isinstance(tier, dict) else tier)
            for name, tier in (getattr(config.squilla_router, "tiers", {}) or {}).items()
        }
        public_payload["mode"] = "disabled"
        public_payload.update({"enabled": False, "tier_profile": None})
    else:
        preset = get_preset(provider)
        active_model = str(getattr(config.llm, "model", "") or "").strip()
        base_tiers = _preset_tiers_with_model(preset, active_model) if preset is not None else {}
        source_tiers = tiers
        if router_mode == "openrouter-mix":
            if provider != "openrouter":
                raise ValueError(
                    "openrouter-mix router mode is only valid for openrouter LLM provider"
                )
            source_tiers = (
                tiers if tiers is not None else getattr(config.squilla_router, "tiers", {})
            )
        elif router_mode == "custom" and tiers is None:
            # No tiers passed: an inline (possibly hand-edited) ladder —
            # including one preserved across a disable — is the effective
            # state, so keep it rather than resetting to the preset base.
            stored_tiers = getattr(config.squilla_router, "tiers", {}) or {}
            if (
                getattr(config.squilla_router, "tier_profile", None) is None
                and stored_tiers
                and not _tiers_equal_after_canonical_normalization(
                    stored_tiers, _default_tiers()
                )
            ):
                source_tiers = stored_tiers
        merged_tiers = _merge_router_tiers(base_tiers, source_tiers)
        if preset is None:
            # A hand-edited, non-registry llm.provider has no packaged
            # profile to seed tiers from; unless the caller supplied a full
            # ladder, the advertised router one-liner would otherwise die on
            # the cryptic "router tier 'c0' must be an object".
            missing_tiers = [
                tier_name
                for tier_name in _TEXT_ROUTER_TIERS
                if not isinstance(merged_tiers.get(tier_name), dict)
            ]
            if missing_tiers:
                raise ValueError(
                    f"llm.provider {provider!r} is not a registered provider, so no "
                    f"packaged router profile can seed tiers "
                    f"{', '.join(missing_tiers)}. Configure a registered provider "
                    f"first (opensquilla onboard configure provider --provider "
                    f"<id>) or disable the router (opensquilla onboard configure "
                    f"router --router disabled)."
                )
        writes_packaged_profile = (
            router_mode in {"recommended", "openrouter-mix"}
            and preset is not None
            and preset.persistable
            and _tiers_equal_after_canonical_normalization(merged_tiers, base_tiers)
        )
        if writes_packaged_profile:
            router_payload["enabled"] = True
            router_payload["tier_profile"] = provider
            router_payload["tiers"] = merged_tiers
            public_payload["mode"] = "recommended"
            public_payload.update({"enabled": True, "tier_profile": provider})
        else:
            router_payload["enabled"] = True
            router_payload["tier_profile"] = None
            router_payload["tiers"] = merged_tiers
            public_payload["mode"] = "custom"
            public_payload.update({"enabled": True, "tier_profile": None})
    warnings: list[str] = []
    if router_payload.get("enabled"):
        _validate_router_tiers(
            cast(dict[str, Any], router_payload.get("tiers") or {}),
            default_tier_clean,
        )
        warnings = _cross_provider_tier_warnings(
            cast(dict[str, Any], router_payload.get("tiers") or {}),
            provider,
            cross_provider_enabled=bool(router_payload.get("cross_provider_tiers")),
            llm_profiles=getattr(config, "llm_profiles", None),
        )

    new_cfg = _clone(config)
    new_cfg.squilla_router = SquillaRouterConfig(**router_payload)
    _sync_llm_model_to_router_default(new_cfg)
    public_payload["default_tier"] = new_cfg.squilla_router.default_tier
    public_payload["tiers"] = redact_router_tiers_payload(new_cfg.squilla_router.tiers)
    public_payload["cross_provider_tiers"] = bool(new_cfg.squilla_router.cross_provider_tiers)
    public_payload["tier_provider_mismatch"] = new_cfg.squilla_router.tier_provider_mismatch
    return MutationResult(
        config=new_cfg,
        changed=True,
        restart_required=False,
        warnings=warnings,
        public_payload=public_payload,
    )


# Values the RPC surface may write into [llm_ensemble]. Sourced from the
# config model's own Literal annotations so the mutation can never drift
# from what GatewayConfig actually accepts.
_LLM_ENSEMBLE_SELECTION_MODES: tuple[str, ...] = tuple(
    str(value)
    for value in get_args(LlmEnsembleConfig.model_fields["selection_mode"].annotation)
)
_LLM_ENSEMBLE_ALL_FAILED_POLICIES: tuple[str, ...] = tuple(
    str(value)
    for value in get_args(LlmEnsembleConfig.model_fields["all_failed_policy"].annotation)
)


def upsert_llm_ensemble(
    config: GatewayConfig,
    *,
    enabled: bool | None = None,
    selection_mode: str | None = None,
    model_options: list[str] | None = None,
    candidates: list[dict[str, object]] | None = None,
    min_successful_proposers: int | str | None = None,
    all_failed_policy: str | None = None,
) -> MutationResult:
    """Update the ``[llm_ensemble]`` routing surface.

    Partial-payload semantics are pinned: the merge seeds from the *current*
    ``llm_ensemble`` section and overrides only the keys explicitly present
    in the request (``None`` = keep current). Omitted keys must never reset
    to defaults — an enabled-only save from a client must not clobber an
    operator's explicit ``selection_mode`` or ``model_options``.

    The TurnRunner reads ``llm_ensemble`` live from the running config, so
    no restart is required.
    """
    current = config.llm_ensemble.model_dump(mode="python")
    merged = dict(current)

    if enabled is not None:
        merged["enabled"] = bool(enabled)
    if selection_mode is not None:
        mode_clean = str(selection_mode).strip()
        if mode_clean not in _LLM_ENSEMBLE_SELECTION_MODES:
            raise ValueError(
                "selection_mode must be one of: "
                + ", ".join(_LLM_ENSEMBLE_SELECTION_MODES)
            )
        merged["selection_mode"] = mode_clean
    if model_options is not None:
        if not isinstance(model_options, (list, tuple)):
            raise ValueError("model_options must be a list of model ids")
        merged["model_options"] = [str(option) for option in model_options]
    if candidates is not None:
        if not isinstance(candidates, (list, tuple)):
            raise ValueError("candidates must be a list of candidate objects")
        candidate_payloads: list[dict[str, object]] = []
        for entry in candidates:
            if not isinstance(entry, dict):
                raise ValueError("candidates must be a list of candidate objects")
            candidate_payloads.append(dict(entry))
        merged["candidates"] = candidate_payloads
    if min_successful_proposers is not None:
        merged["min_successful_proposers"] = _positive_int(
            min_successful_proposers, label="min_successful_proposers"
        )
    if all_failed_policy is not None:
        policy_clean = str(all_failed_policy).strip()
        if policy_clean not in _LLM_ENSEMBLE_ALL_FAILED_POLICIES:
            raise ValueError(
                "all_failed_policy must be one of: "
                + ", ".join(_LLM_ENSEMBLE_ALL_FAILED_POLICIES)
            )
        merged["all_failed_policy"] = policy_clean

    try:
        new_ensemble = LlmEnsembleConfig(**merged)
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc

    new_cfg = _clone(config)
    new_cfg.llm_ensemble = new_ensemble
    if enabled is not None:
        # An explicit enabled/disabled decision must be visible in the file
        # even when it equals the model default — otherwise a headless
        # `configure ensemble --disabled` on a fresh config persists nothing
        # and is indistinguishable from a silent no-op.
        new_cfg.mark_force_persist("llm_ensemble.enabled")

    payload: dict[str, Any] = {
        "enabled": new_ensemble.enabled,
        "selection_mode": new_ensemble.selection_mode,
        "model_options": list(new_ensemble.model_options),
        "min_successful_proposers": new_ensemble.min_successful_proposers,
        "all_failed_policy": new_ensemble.all_failed_policy,
    }
    if candidates is not None or new_ensemble.candidates:
        payload["candidates"] = [
            candidate.model_dump(mode="python")
            for candidate in new_ensemble.candidates
        ]
    return MutationResult(
        config=new_cfg,
        changed=current != new_ensemble.model_dump(mode="python"),
        restart_required=False,
        warnings=[],
        public_payload=payload,
    )


def upsert_search_provider(
    config: GatewayConfig,
    *,
    provider_id: str,
    api_key: str | None = None,
    api_key_env: str | None = None,
    max_results: int | str | None = None,
    proxy: str | None = None,
    use_env_proxy: bool | None = None,
    fallback_policy: str | None = None,
    diagnostics: bool | None = None,
) -> MutationResult:
    """Save the web search provider configuration.

    Keep-current contract (``None`` = "not passed"): ``max_results``,
    ``proxy``, ``use_env_proxy``, ``fallback_policy``, and ``diagnostics``
    keep their currently stored values when omitted — these are global
    search settings, so keep-current applies even when ``provider_id``
    changes. Explicit values always win (``proxy=""`` clears the proxy).
    A blank ``api_key`` keeps the stored key when re-saving the provider
    that is already active.
    """
    spec = get_search_provider_setup_spec(provider_id)
    if not spec.runtime_supported:
        raise ValueError(
            f"search provider {provider_id!r} is not runtime-supported and cannot be configured"
        )
    api_key = api_key or ""
    api_key_env = api_key_env or ""
    if max_results is None:
        effective_max_results = int(config.search_max_results)
    else:
        # Cap the write side to the same ceiling the config field enforces so
        # an over-range request is clamped here with a clear path rather than
        # failing late with a raw validation error at persist time.
        effective_max_results = min(
            _positive_int(max_results, label="max_results"), MAX_SEARCH_RESULTS
        )
    if fallback_policy is None:
        fallback_policy_value = cast(SearchFallbackPolicy, config.search_fallback_policy)
    else:
        if fallback_policy not in {"off", "network"}:
            raise ValueError("fallback_policy must be 'off' or 'network'")
        fallback_policy_value = cast(SearchFallbackPolicy, fallback_policy)
    effective_proxy = str(config.search_proxy or "") if proxy is None else proxy
    effective_use_env_proxy = (
        bool(config.search_use_env_proxy) if use_env_proxy is None else bool(use_env_proxy)
    )
    effective_diagnostics = (
        bool(config.search_diagnostics) if diagnostics is None else bool(diagnostics)
    )

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
    new_cfg.search_proxy = effective_proxy
    new_cfg.search_use_env_proxy = effective_use_env_proxy
    new_cfg.search_fallback_policy = fallback_policy_value
    new_cfg.search_diagnostics = effective_diagnostics
    if api_key:
        clear_runtime_secret_paths(new_cfg, {"search_api_key"})

    api_key_source = (
        "explicit" if effective_api_key else ("env" if effective_api_key_env else "none")
    )
    payload = {
        "provider": provider_id,
        "api_key": effective_api_key,
        "api_key_env": effective_api_key_env,
        "api_key_source": api_key_source,
        "max_results": effective_max_results,
        "proxy": effective_proxy,
        "use_env_proxy": effective_use_env_proxy,
        "fallback_policy": fallback_policy_value,
        "diagnostics": effective_diagnostics,
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


ImageOutputFormat = Literal["png", "jpeg", "webp"]
_VALID_IMAGE_SIZES = ("1024x1024", "1536x1024", "1024x1536")
_VALID_IMAGE_OUTPUT_FORMATS: tuple[ImageOutputFormat, ...] = ("png", "jpeg", "webp")


def upsert_image_generation_provider(
    config: GatewayConfig,
    *,
    provider_id: str,
    primary: str = "",
    api_key: str = "",
    api_key_env: str = "",
    base_url: str = "",
    enabled: bool = True,
    size: str = "",
    output_format: str = "",
    fallbacks: list[str] | None = None,
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

    # size/output_format are constrained; empty keeps the current value.
    effective_size = (size or "").strip() or config.image_generation.size
    if effective_size not in _VALID_IMAGE_SIZES:
        raise ValueError(
            f"image size must be one of {', '.join(_VALID_IMAGE_SIZES)}"
        )
    effective_output_format = (output_format or "").strip() or config.image_generation.output_format
    if effective_output_format not in _VALID_IMAGE_OUTPUT_FORMATS:
        raise ValueError(
            f"image output format must be one of {', '.join(_VALID_IMAGE_OUTPUT_FORMATS)}"
        )
    # fallbacks: each must be a provider/model reference; an empty list keeps current.
    cleaned_fallbacks = [f.strip() for f in (fallbacks or []) if f and f.strip()]
    for fb in cleaned_fallbacks:
        if "/" not in fb:
            raise ValueError(
                f"image fallback {fb!r} must be a provider/model reference"
            )
    effective_fallbacks = cleaned_fallbacks or list(config.image_generation.fallbacks)

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
    # The enabled decision is explicit at this layer (callers resolve
    # keep-current before invoking): force it into the file even when it
    # equals the model default, otherwise a first-time enabled=false is
    # dropped by the sparse persist and a later key rotation flips the tool
    # back on via the legacy configure-implies-enable fallback.
    new_cfg.mark_force_persist("image_generation.enabled")
    new_cfg.image_generation.primary = primary_model
    new_cfg.image_generation.size = effective_size
    new_cfg.image_generation.output_format = cast(ImageOutputFormat, effective_output_format)
    new_cfg.image_generation.fallbacks = effective_fallbacks
    next_provider_cfg = _image_generation_provider_config(new_cfg, provider_id)
    next_provider_cfg.api_key = effective_api_key
    next_provider_cfg.api_key_env = env_key
    next_provider_cfg.base_url = effective_base_url
    if api_key:
        clear_runtime_secret_paths(
            new_cfg, {f"image_generation.providers.{provider_id}.api_key"}
        )

    payload = {
        "provider": provider_id,
        "enabled": bool(enabled),
        "primary": primary_model,
        "api_key": effective_api_key,
        "api_key_env": env_key,
        "api_key_source": api_key_source,
        "base_url": effective_base_url,
        "size": effective_size,
        "output_format": effective_output_format,
        "fallbacks": effective_fallbacks,
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
    # Explicit off switch: must land in the file even on a fresh config where
    # it equals the model default, so a later provider save that omits the
    # flag keeps it off instead of re-enabling via configure-implies-enable.
    new_cfg.mark_force_persist("image_generation.enabled")
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
        clear_runtime_secret_paths(new_cfg, {f"audio.providers.{provider_id}.api_key"})

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
        clear_runtime_secret_paths(
            new_cfg,
            {"memory.embedding.remote.api_key", "memory.embedding.api_key"},
        )

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


def _format_channel_validation_error(exc: ValidationError) -> str:
    """Render a channel-entry ValidationError as a field-naming summary.

    Never echoes pydantic's ``input_value`` dump: channel payloads carry
    credentials (bot tokens, app secrets) and this message surfaces on
    stderr and RPC error responses. Only field paths and validator messages
    are included, with the free-text redactor as a final guard.
    """
    parts: list[str] = []
    for error in exc.errors(include_url=False, include_context=False, include_input=False):
        loc = ".".join(str(item) for item in error.get("loc", ()) or ())
        msg = str(error.get("msg") or "invalid value")
        parts.append(f"{loc}: {msg}" if loc else msg)
    detail = "; ".join(parts) or "invalid value"
    return f"invalid channel entry: {redact_error_text(detail, max_len=500)}"


def _require_non_blank_secret_fields(type_name: str, entry: Mapping[str, Any]) -> None:
    """Reject blank required credential fields at mutation time.

    An empty or whitespace-only secret (e.g. ``--field token=``) would
    otherwise persist cleanly and only fail much later at gateway start.
    Fields gated by ``show_when`` are checked only when their condition
    matches the normalized entry.
    """
    from opensquilla.onboarding.channel_specs import get_channel_setup_spec

    try:
        spec = get_channel_setup_spec(type_name)
    except KeyError:
        return
    for field_spec in spec.fields:
        if not (field_spec.required and field_spec.secret):
            continue
        if field_spec.show_when and not all(
            str(entry.get(key, "")) == str(expected)
            for key, expected in field_spec.show_when.items()
        ):
            continue
        value = entry.get(field_spec.name)
        if value is None or not str(value).strip():
            raise ValueError(
                f"channel field {field_spec.name!r} requires a non-empty value"
            )


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
        raise ValueError(_format_channel_validation_error(exc)) from exc
    normalized = entry.model_dump(mode="python")
    _require_non_blank_secret_fields(type_name, normalized)
    if (
        type_name == "slack"
        and getattr(entry, "connection_mode", "webhook") == "webhook"
        and not str(getattr(entry, "signing_secret", "") or "").strip()
    ):
        raise ValueError("slack webhook channels require signing_secret")
    return normalized


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
        provided = merged.get(f.name)
        blank = provided is None or (isinstance(provided, str) and not provided.strip())
        if blank and existing.get(f.name):
            merged[f.name] = existing[f.name]
    return merged


def merge_channel_entry_secrets(
    config: GatewayConfig, payload: dict[str, Any]
) -> dict[str, Any]:
    """Public wrapper over the blank-secret keep-current merge.

    Lets validation-only surfaces (gateway ``onboarding.channel.probe``)
    resolve blank secrets against the stored entry exactly the way
    ``upsert_channel`` does, so a probe of a keep-current payload does not
    hard-fail on the non-blank-secret requirement that the subsequent upsert
    would satisfy via the merge.
    """
    return _merge_with_existing_secrets(config, payload)


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
