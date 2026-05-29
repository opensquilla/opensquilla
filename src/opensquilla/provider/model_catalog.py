"""ModelCatalog — in-memory cache of model metadata fetched from provider API."""

from __future__ import annotations

import httpx
import structlog

from opensquilla.env import trust_env as _trust_env
from opensquilla.secrets import clean_header_secret

from .openrouter_attribution import openrouter_app_headers
from .registry import UnknownProviderError, get_provider_spec
from .types import ModelCapabilities, ModelInfo

log = structlog.get_logger(__name__)

DEFAULT_MAX_TOKENS = 16384
SAFE_OPENROUTER_DEFAULT_MAX_TOKENS = 8192
DEFAULT_CONTEXT_WINDOW = 200_000

# Static fallback for squilla-router tier models + default model.
# Used when OpenRouter API is unreachable at boot.
# Format: model_id → (max_output_tokens, context_window)
_STATIC_FALLBACK: dict[str, tuple[int, int]] = {
    "gpt-5.4-nano": (128_000, 400_000),
    "gpt-5.4-mini": (128_000, 400_000),
    "gpt-5.5": (128_000, 1_000_000),
    "minimax/minimax-m2.7": (8192, 196_608),
    "stepfun/step-3.5-flash": (16_384, 256_000),
    "z-ai/glm-4.5-air": (98_304, 131_072),
    "minimax/minimax-m2.5": (65_536, 196_608),
    "deepseek/deepseek-v4-flash": (16_384, 1_048_576),
    "deepseek/deepseek-v4-pro": (16_384, 1_048_576),
    "deepseek-v4-flash": (393_216, 1_048_576),
    "deepseek-v4-pro": (393_216, 1_048_576),
    "deepseek/deepseek-v3.2": (16_384, 163_840),
    "glm-4.7-flashx": (128_000, 200_000),
    "glm-5": (128_000, 200_000),
    "glm-5.1": (128_000, 200_000),
    "z-ai/glm-5": (80_000, 80_000),
    "z-ai/glm-5.1": (202_752, 202_752),
    "moonshot-v1-8k": (8192, 8192),
    "moonshot-v1-32k": (32_768, 32_768),
    "moonshot-v1-128k": (131_072, 131_072),
    "kimi-k2.5": (32_768, 262_144),
    "kimi-k2.6": (32_768, 262_144),
    "moonshotai/kimi-k2.6": (DEFAULT_MAX_TOKENS, 262_142),
    "moonshotai/kimi-k2.5": (65_535, 262_144),
}


class ModelCatalog:
    """In-memory cache of model metadata fetched from provider API.

    Priority chain for max_tokens:
      1. User config override (>0)
      2. API-fetched catalog value
      3. Static fallback table
      4. DEFAULT_MAX_TOKENS (16384)
      → then clamp to min(value, context_window)
    """

    def __init__(self) -> None:
        self._models: dict[str, ModelInfo] = {}

    def __len__(self) -> int:
        return len(self._models)

    def _populate_from_data(self, models: list[dict]) -> None:
        """Parse a list of OpenRouter model dicts into ModelInfo entries."""
        for m in models:
            model_id = m.get("id", "")
            if not model_id:
                continue
            top_provider = m.get("top_provider") or {}
            max_completion = top_provider.get("max_completion_tokens") or 0
            supported = set(m.get("supported_parameters", []))
            architecture = m.get("architecture") or {}
            input_modalities = {
                str(item).lower() for item in architecture.get("input_modalities", [])
            }
            self._models[model_id] = ModelInfo(
                provider="openrouter",
                model_id=model_id,
                display_name=m.get("name", model_id),
                context_window=m.get("context_length", 0),
                max_output_tokens=max_completion,
                supports_reasoning="reasoning" in supported or "reasoning_effort" in supported,
                supports_tools="tools" in supported or "tool_choice" in supported,
                supports_vision="image" in input_modalities,
            )

    def get_capabilities(
        self,
        model_id: str,
        provider_name: str = "openrouter",
        base_url: str = "",
    ) -> ModelCapabilities:
        """Resolve ModelCapabilities for a model based on provider and catalog data."""
        if provider_name == "anthropic":
            return ModelCapabilities()
        if provider_name == "ollama":
            return ModelCapabilities()
        provider_id = provider_name.strip().lower()
        try:
            provider_spec = get_provider_spec(provider_id)
        except UnknownProviderError:
            provider_spec = None

        if provider_name == "openai" and "deepseek" in base_url.lower():
            return ModelCapabilities(
                supports_reasoning=True, supports_tools=True, reasoning_format="deepseek"
            )
        info = self._models.get(model_id)
        if info and info.supports_reasoning:
            return ModelCapabilities(
                supports_reasoning=True,
                supports_tools=info.supports_tools,
                supports_vision=info.supports_vision,
                reasoning_format="openrouter",
            )
        model_l = model_id.strip().lower()
        if (
            provider_name == "openai"
            and "api.openai.com" in base_url.lower()
            and model_l.startswith(("gpt-5", "o1", "o3", "o4"))
        ):
            return ModelCapabilities(
                supports_reasoning=True,
                supports_tools=True,
                reasoning_format="openai",
            )
        if provider_spec and provider_spec.reasoning_shape == "deepseek":
            return ModelCapabilities(
                supports_reasoning=True,
                supports_tools=True,
                reasoning_format="deepseek",
            )
        if provider_spec and provider_spec.reasoning_shape == "gemini":
            supports_reasoning = model_l.startswith("gemini-2.5")
            return ModelCapabilities(
                supports_reasoning=supports_reasoning,
                supports_tools=True,
                supports_vision=True,
                reasoning_format="gemini" if supports_reasoning else "none",
            )
        if provider_spec and provider_spec.reasoning_shape == "zai":
            supports_reasoning = model_l.startswith(("glm-4.5", "glm-4.7", "glm-5"))
            return ModelCapabilities(
                supports_reasoning=supports_reasoning,
                supports_tools=True,
                reasoning_format="zai" if supports_reasoning else "none",
            )
        if provider_id == "dashscope":
            supports_reasoning = model_l.startswith(
                (
                    "qwen3",
                    "qwen-plus",
                    "qwen-flash",
                    "qwen-turbo",
                    "qwen-max",
                    "qwq",
                )
            )
            return ModelCapabilities(
                supports_reasoning=supports_reasoning,
                supports_tools=True,
                supports_vision=model_l.startswith(("qwen3.5", "qwen3.6", "qwen-vl")),
                reasoning_format="dashscope" if supports_reasoning else "none",
            )
        if provider_id == "moonshot":
            supports_reasoning = model_l.startswith(
                ("kimi-k2.5", "kimi-k2.6", "kimi-k2-thinking")
            )
            return ModelCapabilities(
                supports_reasoning=supports_reasoning,
                supports_tools=True,
                supports_vision=model_l.startswith(("kimi-k2.5", "kimi-k2.6")),
                reasoning_format="moonshot" if supports_reasoning else "none",
            )
        if provider_id in {"volcengine", "byteplus"}:
            supports_reasoning = (
                "thinking" in model_l
                or model_l.startswith("doubao-seed-2")
                or model_l.startswith("doubao-seed-1-8")
            )
            return ModelCapabilities(
                supports_reasoning=supports_reasoning,
                supports_tools=True,
                supports_vision=model_l.startswith(("doubao-seed-1-8", "doubao-seed-2")),
                reasoning_format="volcengine" if supports_reasoning else "none",
            )
        return ModelCapabilities(
            supports_tools=info.supports_tools if info else True,
            supports_vision=info.supports_vision if info else False,
        )

    async def fetch_openrouter(self, api_key: str, base_url: str, proxy: str = "") -> None:
        """Fetch model list from OpenRouter /api/v1/models endpoint.

        ``base_url`` MUST NOT end with ``/v1`` — boot.py strips it.
        URL constructed as: ``f"{base_url}/v1/models"``
        """
        url = f"{base_url}/v1/models"
        headers = {
            "Authorization": f"Bearer {clean_header_secret(api_key, label='OpenRouter API key')}"
        }
        headers.update(openrouter_app_headers(base_url))
        async with httpx.AsyncClient(
            timeout=10.0, trust_env=_trust_env(), proxy=proxy or None
        ) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        self._populate_from_data(data.get("data", []))
        log.debug("model_catalog.fetched", count=len(self._models))

    def get(self, model_id: str) -> ModelInfo | None:
        """Look up model metadata by ID."""
        return self._models.get(model_id)

    def resolve_max_tokens(self, model_id: str, user_override: int = 0) -> int:
        """Resolve max_tokens: user > catalog > static fallback > default, then clamp."""
        context_window = self.resolve_context_window(model_id)
        info = self._models.get(model_id)

        using_user_override = user_override > 0
        if using_user_override:
            effective = user_override
        elif info and info.max_output_tokens > 0:
            effective = info.max_output_tokens
        elif model_id in _STATIC_FALLBACK:
            effective = _STATIC_FALLBACK[model_id][0]
        else:
            effective = DEFAULT_MAX_TOKENS

        # Clamp to context window. Some provider catalogs report a model's
        # max_completion_tokens as almost the entire context window; using that
        # value as max_tokens leaves no room for ordinary prompt/tool/image input
        # and causes preventable context-limit failures.
        if context_window > 0:
            effective = min(effective, context_window)
            if (
                not using_user_override
                and context_window > DEFAULT_MAX_TOKENS
                and effective >= context_window - DEFAULT_MAX_TOKENS
            ):
                effective = min(effective, SAFE_OPENROUTER_DEFAULT_MAX_TOKENS)

        return effective

    def resolve_context_window(self, model_id: str) -> int:
        """Resolve context window: catalog > static fallback > default."""
        info = self._models.get(model_id)
        if info and info.context_window > 0:
            return info.context_window
        if model_id in _STATIC_FALLBACK:
            return _STATIC_FALLBACK[model_id][1]
        return DEFAULT_CONTEXT_WINDOW
