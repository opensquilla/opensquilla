"""Runtime LLM provider credential resolution."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

OPENROUTER_DEFAULT_PROVIDER_ROUTING = {
    "anthropic/claude-opus-4.8": "anthropic",
    "anthropic/claude-sonnet-4.6": "anthropic",
    "deepseek/deepseek-v4-flash": "deepseek",
    "google/gemini-3.5-flash": "google",
    "moonshotai/kimi-k2.6": "moonshotai",
    "openai/gpt-5.4-mini": "openai",
    "openai/gpt-5.5": "openai",
    "qwen/qwen3-coder-plus": "qwen",
    "x-ai/grok-4.3": "x-ai",
    "z-ai/glm-4.6": "z-ai",
    "z-ai/glm-5.1": "z-ai",
    "z-ai/glm-5.2": "z-ai",
}


@dataclass(frozen=True)
class LlmRuntimeConfig:
    provider: str
    model: str
    api_key: str
    base_url: str
    proxy: str
    provider_routing: dict[str, str]
    api_key_from_env: bool = False
    base_url_from_env: bool = False


def provider_base_url_env_name(provider: str) -> str:
    from opensquilla.provider.registry import get_provider_spec

    spec = get_provider_spec(provider)
    if spec.env_key.endswith("_API_KEY"):
        return f"{spec.env_key.removesuffix('_API_KEY')}_BASE_URL"
    normalized = spec.provider_id.upper().replace("-", "_")
    return f"{normalized}_BASE_URL"


def _resolve_provider_routing(provider: str, configured: Any) -> dict[str, str]:
    routing = dict(configured or {})
    if provider != "openrouter":
        return routing
    return {**OPENROUTER_DEFAULT_PROVIDER_ROUTING, **routing}


def resolve_llm_runtime_config(config: Any) -> LlmRuntimeConfig:
    """Resolve provider credentials from provider-specific env before config."""
    from opensquilla.provider.registry import get_provider_spec

    llm = config.llm
    provider = str(llm.provider or "").strip().lower()
    spec = get_provider_spec(provider)
    runtime_secret_paths: set[str] = getattr(config, "_runtime_secret_paths", set())
    explicit_api_key = llm.api_key if "llm.api_key" not in runtime_secret_paths else ""
    api_key_env_name = "" if explicit_api_key else (getattr(llm, "api_key_env", "") or spec.env_key)
    base_url_env_name = provider_base_url_env_name(provider)
    env_api_key = os.environ.get(api_key_env_name, "") if api_key_env_name else ""
    env_base_url = os.environ.get(base_url_env_name, "")
    api_key = explicit_api_key or env_api_key or llm.api_key
    base_url = env_base_url or llm.base_url or spec.default_base_url
    proxy = os.environ.get("OPENSQUILLA_LLM_PROXY", "") or getattr(llm, "proxy", "")

    llm.provider = provider
    llm.api_key = api_key
    llm.base_url = base_url
    llm.proxy = proxy
    if env_api_key and hasattr(config, "mark_runtime_secret"):
        config.mark_runtime_secret("llm.api_key")

    return LlmRuntimeConfig(
        provider=provider,
        model=llm.model,
        api_key=api_key,
        base_url=base_url,
        proxy=proxy,
        provider_routing=_resolve_provider_routing(
            provider,
            getattr(llm, "provider_routing", {}),
        ),
        api_key_from_env=bool(env_api_key),
        base_url_from_env=bool(env_base_url),
    )
