"""Process-wide image generation runtime configuration."""

from __future__ import annotations

import os
from typing import Any

from opensquilla.provider.image_generation import (
    get_image_generation_provider,
    list_image_generation_providers,
    parse_image_generation_model_ref,
    reset_image_generation_providers,
)
from opensquilla.provider.image_generation_config import ImageGenerationConfig

_image_generation_config: Any | None = None


def configure_image_generation(config: Any | None, *, llm_config: Any | None = None) -> None:
    global _image_generation_config
    _image_generation_config = config
    reset_image_generation_providers(config, llm_config=llm_config)


def current_image_generation_config() -> Any:
    if _image_generation_config is not None:
        return _image_generation_config
    return ImageGenerationConfig()


def resolve_image_generation_candidates(model: str | None, config: Any) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()

    def add(raw: str | None) -> None:
        if raw and raw not in seen:
            seen.add(raw)
            candidates.append(raw)

    add(model)
    add(getattr(config, "primary", None))
    for fallback in getattr(config, "fallbacks", []) or []:
        add(fallback)
    primary = getattr(config, "primary", None)
    fallbacks = getattr(config, "fallbacks", []) or []
    has_explicit_model_routing = (
        bool(model) or bool(fallbacks) or bool(primary and primary != "openai/gpt-image-1")
    )
    if not has_explicit_model_routing:
        for provider in list_image_generation_providers():
            if image_generation_provider_has_auth(provider):
                add(f"{provider.provider_id}/{provider.default_model}")
    return candidates


def image_generation_available(config: Any | None = None) -> bool:
    """Return whether image generation has at least one configured provider."""
    resolved_config = config if config is not None else current_image_generation_config()
    if not getattr(resolved_config, "enabled", False):
        return False

    for candidate in resolve_image_generation_candidates(None, resolved_config):
        try:
            provider_id, _model = parse_image_generation_model_ref(candidate)
        except ValueError:
            continue
        provider = get_image_generation_provider(provider_id)
        if provider is not None and image_generation_provider_has_auth(provider):
            return True
    return False


def image_generation_provider_has_auth(provider: Any) -> bool:
    resolve_api_key = getattr(provider, "_resolve_api_key", None)
    if callable(resolve_api_key):
        try:
            return bool(resolve_api_key())
        except Exception:  # noqa: BLE001 - capability checks must be non-fatal
            return False

    auth_env_vars = tuple(getattr(provider, "auth_env_vars", ()) or ())
    if not auth_env_vars:
        return True
    return any(bool(os.environ.get(env_var)) for env_var in auth_env_vars)
