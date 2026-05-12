"""Derive a structured OnboardingStatus from a GatewayConfig."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from opensquilla.gateway.config import GatewayConfig
from opensquilla.onboarding.config_store import default_config_path
from opensquilla.onboarding.image_generation_specs import (
    get_image_generation_provider_setup_spec,
    list_image_generation_provider_setup_specs,
)
from opensquilla.onboarding.provider_specs import get_provider_setup_spec


@dataclass(frozen=True)
class OnboardingStatus:
    config_path: str | None
    has_config: bool
    llm_configured: bool
    llm_source: str
    image_generation_configured: bool
    image_generation_enabled: bool
    image_generation_source: str
    image_generation_provider: str
    image_generation_primary: str
    search_configured: bool
    channel_count: int
    channels_configured: bool
    needs_onboarding: bool
    warnings: tuple[str, ...] = ()


def _llm_status(cfg: GatewayConfig) -> tuple[bool, str]:
    llm = cfg.llm
    if not llm.provider or not llm.model:
        return False, "none"
    try:
        spec = get_provider_setup_spec(llm.provider)
    except KeyError:
        return False, "none"
    if not spec.runtime_supported:
        return False, "none"
    if spec.requires_base_url and not llm.base_url:
        return False, "none"
    if not spec.requires_api_key:
        return True, "none"
    if llm.api_key and "llm.api_key" not in getattr(
        cfg, "_runtime_secret_paths", set()
    ):
        return True, "explicit"
    env_key = getattr(llm, "api_key_env", "").strip()
    if env_key and os.environ.get(env_key):
        return True, "env"
    if env_key:
        return False, "missing_env"
    return False, "none"


def _search_configured(cfg: GatewayConfig) -> bool:
    return True


def _image_generation_provider_config(cfg: GatewayConfig, provider_id: str) -> object | None:
    providers = getattr(getattr(cfg, "image_generation", None), "providers", None)
    return getattr(providers, provider_id, None) if providers is not None else None


def _image_generation_provider_source(
    cfg: GatewayConfig,
    provider_id: str,
) -> tuple[str, str]:
    try:
        spec = get_image_generation_provider_setup_spec(provider_id)
    except KeyError:
        return "", ""

    provider_cfg = _image_generation_provider_config(cfg, provider_id)
    explicit_key = getattr(provider_cfg, "api_key", "") if provider_cfg else ""
    if explicit_key:
        return "explicit", spec.env_key

    env_key = getattr(provider_cfg, "api_key_env", spec.env_key) if provider_cfg else spec.env_key
    if env_key and os.environ.get(env_key):
        return "env", env_key

    llm = getattr(cfg, "llm", None)
    if getattr(llm, "provider", "").strip().lower() == provider_id and getattr(llm, "api_key", ""):
        return "llm_fallback", spec.env_key
    return "", spec.env_key


def _configured_image_generation_provider_ids(cfg: GatewayConfig) -> list[str]:
    image_cfg = cfg.image_generation
    refs: list[str] = []
    primary = getattr(image_cfg, "primary", "")
    fallbacks = list(getattr(image_cfg, "fallbacks", []) or [])
    default_primary = "openai/gpt-image-1"
    explicit_model_routing = bool(fallbacks) or bool(primary and primary != default_primary)
    if explicit_model_routing:
        refs = [primary, *fallbacks]
    else:
        refs = [
            spec.default_model
            for spec in list_image_generation_provider_setup_specs()
            if spec.runtime_supported
        ]

    provider_ids: list[str] = []
    seen: set[str] = set()
    for ref in refs:
        provider_id, sep, _model = ref.partition("/")
        provider_id = provider_id.strip()
        if sep and provider_id and provider_id not in seen:
            seen.add(provider_id)
            provider_ids.append(provider_id)
    return provider_ids


def _image_generation_status(
    cfg: GatewayConfig,
) -> tuple[bool, bool, str, str, str]:
    image_cfg = cfg.image_generation
    enabled = bool(getattr(image_cfg, "enabled", False))
    primary = getattr(image_cfg, "primary", "")
    if not enabled:
        return False, False, "none", "", primary

    for provider_id in _configured_image_generation_provider_ids(cfg):
        source, _env_key = _image_generation_provider_source(cfg, provider_id)
        if source:
            return True, True, source, provider_id, primary
    return False, True, "none", "", primary


def get_onboarding_status(config: GatewayConfig) -> OnboardingStatus:
    path = Path(config.config_path).expanduser() if config.config_path else default_config_path()
    has_config = path.exists()
    llm_ok, llm_source = _llm_status(config)
    (
        image_ok,
        image_enabled,
        image_source,
        image_provider,
        image_primary,
    ) = _image_generation_status(config)
    enabled_channels = [c for c in config.channels.channels if c.enabled]
    return OnboardingStatus(
        config_path=str(path),
        has_config=has_config,
        llm_configured=llm_ok,
        llm_source=llm_source,
        image_generation_configured=image_ok,
        image_generation_enabled=image_enabled,
        image_generation_source=image_source,
        image_generation_provider=image_provider,
        image_generation_primary=image_primary,
        search_configured=_search_configured(config),
        channel_count=len(config.channels.channels),
        channels_configured=bool(enabled_channels),
        needs_onboarding=not llm_ok,
    )
