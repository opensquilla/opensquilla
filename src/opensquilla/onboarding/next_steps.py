"""Secret-safe next-step text for onboarding output."""

from __future__ import annotations

import os
import platform
from pathlib import Path
from typing import Any

from opensquilla.onboarding.image_generation_specs import (
    get_image_generation_provider_setup_spec,
)
from opensquilla.onboarding.search_specs import get_search_provider_setup_spec
from opensquilla.onboarding.status import get_onboarding_status

_KEY_URLS = {
    "openrouter": "https://openrouter.ai/keys",
    "openai": "https://platform.openai.com/api-keys",
    "anthropic": "https://console.anthropic.com/settings/keys",
    "deepseek": "https://platform.deepseek.com/api_keys",
}


def _set_env_hint(env_key: str) -> str:
    if platform.system().lower().startswith("win"):
        return f'PowerShell: $env:{env_key} = "<your-key>"'
    return f'export {env_key}="<your-key>"'


def _missing_env_warning(surface: str, env_key: str) -> str:
    return (
        f"{surface}: ${env_key} is not set in this shell. "
        "The config saved the environment-variable reference, but this feature "
        "will not work until the gateway is started with that variable set."
    )


def _image_generation_provider_id(config: Any) -> str:
    primary = str(getattr(config.image_generation, "primary", "") or "")
    provider_id, sep, _model = primary.partition("/")
    if sep and provider_id:
        return provider_id
    return "openai"


def env_reference_warnings(config: Any) -> list[str]:
    """Return operator-facing warnings for saved env references not visible now."""
    warnings: list[str] = []
    status = get_onboarding_status(config)

    llm = config.llm
    llm_env_key = str(getattr(llm, "api_key_env", "") or "")
    if status.llm_source == "missing_env" and llm_env_key:
        warnings.append(_missing_env_warning("LLM provider", llm_env_key))

    search_provider = str(getattr(config, "search_provider", "") or "")
    search_env_key = str(getattr(config, "search_api_key_env", "") or "")
    if search_provider and search_env_key and not getattr(config, "search_api_key", ""):
        try:
            search_spec = get_search_provider_setup_spec(search_provider)
        except KeyError:
            search_spec = None
        if (
            search_spec is not None
            and search_spec.requires_api_key
            and not os.environ.get(search_env_key)
        ):
            warnings.append(_missing_env_warning("Search provider", search_env_key))

    if status.image_generation_enabled and not status.image_generation_configured:
        provider_id = _image_generation_provider_id(config)
        try:
            image_spec = get_image_generation_provider_setup_spec(provider_id)
        except KeyError:
            image_spec = None
        if image_spec is not None and image_spec.env_key and not os.environ.get(image_spec.env_key):
            warnings.append(_missing_env_warning("Image generation provider", image_spec.env_key))

    return warnings


def format_next_steps(config: Any, *, config_path: str | Path | None = None) -> str:
    status = get_onboarding_status(config)
    llm = config.llm
    router = config.squilla_router
    path = str(config_path or status.config_path or getattr(config, "config_path", ""))
    provider = str(getattr(llm, "provider", "") or "")
    model = str(getattr(llm, "model", "") or "")
    env_key = str(getattr(llm, "api_key_env", "") or "")
    key_source = status.llm_source
    if key_source == "env" and env_key:
        key_line = f"Key: ${env_key}"
    elif key_source == "missing_env" and env_key:
        key_line = f"Key: ${env_key} is not set in this shell"
    elif key_source == "explicit":
        key_line = "Key: stored in config"
    else:
        key_line = "Key: not required" if status.llm_configured else "Key: not configured"

    lines = [
        "Next steps:",
        f"  Config: {path}",
        f"  LLM: {provider} / {model}",
        f"  {key_line}",
        (
            "  Router: disabled"
            if not router.enabled
            else (
                f"  Router: profile={router.tier_profile or 'openrouter-mix'}, "
                f"default={router.default_tier}"
            )
        ),
        "  Start gateway: opensquilla gateway run",
        "  Or start in background: opensquilla gateway start --json",
        "  If a gateway is already running, restart it so it loads this config.",
        "  Restart gateway: opensquilla gateway restart --json",
        "  Web UI: http://127.0.0.1:18790/control/",
    ]
    if key_source == "missing_env" and env_key:
        lines.append(f"  Set key before starting gateway: {_set_env_hint(env_key)}")
    key_url = _KEY_URLS.get(provider)
    if key_url:
        lines.append(f"  Provider keys: {key_url}")
    return "\n".join(lines)
