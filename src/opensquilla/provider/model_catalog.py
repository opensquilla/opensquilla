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


_CONTEXT_WINDOW_FIELDS = (
    "context_length",
    "context_window",
    "max_model_len",
    "max_context_length",
)
_MAX_OUTPUT_FIELDS = ("max_completion_tokens", "max_output_tokens")
_TOOL_PARAMETER_NAMES = {"tools", "tool_choice"}
_TOOL_PROBE_MODES = {"required", "auto"}


def _positive_int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0
    return parsed if parsed > 0 else 0


def _first_positive(row: dict, fields: tuple[str, ...]) -> int:
    for field_name in fields:
        value = _positive_int(row.get(field_name))
        if value > 0:
            return value
    return 0


def _tool_support_state_from_parameters(
    supported_parameters: tuple[str, ...],
) -> str:
    supported = {item.lower() for item in supported_parameters}
    if supported & _TOOL_PARAMETER_NAMES:
        return "supported"
    if supported_parameters:
        return "unsupported"
    return "unknown"


def _normalize_tool_probe_mode(value: object) -> str:
    mode = str(value or "required").strip().lower()
    return mode if mode in _TOOL_PROBE_MODES else "required"


def _normalized_base_url(base_url: str) -> str:
    normalized = base_url.strip().rstrip("/").lower()
    last_segment = normalized.rsplit("/", 1)[-1]
    if len(last_segment) > 1 and last_segment[0] == "v" and last_segment[1:].isdigit():
        return normalized.rsplit("/", 1)[0]
    return normalized


def _provider_model_key(
    provider_name: str,
    base_url: str,
    model_id: str,
) -> tuple[str, str, str]:
    return (provider_name.strip().lower(), _normalized_base_url(base_url), model_id)


def _models_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if not base:
        base = "https://api.openai.com"
    last_segment = base.rsplit("/", 1)[-1].lower()
    if len(last_segment) > 1 and last_segment[0] == "v" and last_segment[1:].isdigit():
        return f"{base}/models"
    return f"{base}/v1/models"


def _chat_completions_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if not base:
        base = "https://api.openai.com"
    last_segment = base.rsplit("/", 1)[-1].lower()
    if len(last_segment) > 1 and last_segment[0] == "v" and last_segment[1:].isdigit():
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"


def model_info_from_openai_compat_row(row: dict, provider_name: str) -> ModelInfo | None:
    model_id = str(row.get("id") or "")
    if not model_id:
        return None
    top_provider = row.get("top_provider") or {}
    top_provider_max = 0
    if isinstance(top_provider, dict):
        top_provider_max = _positive_int(top_provider.get("max_completion_tokens"))
    max_output_tokens = top_provider_max or _first_positive(row, _MAX_OUTPUT_FIELDS)
    supported_parameters = tuple(
        str(item) for item in row.get("supported_parameters", []) if isinstance(item, str)
    )
    tool_support_state = _tool_support_state_from_parameters(supported_parameters)
    supported = {item.lower() for item in supported_parameters}
    architecture = row.get("architecture") or {}
    input_modalities: set[str] = set()
    if isinstance(architecture, dict):
        input_modalities = {str(item).lower() for item in architecture.get("input_modalities", [])}
    return ModelInfo(
        provider=provider_name,
        model_id=model_id,
        display_name=str(row.get("name") or model_id),
        context_window=_first_positive(row, _CONTEXT_WINDOW_FIELDS),
        max_output_tokens=max_output_tokens,
        supports_reasoning="reasoning" in supported or "reasoning_effort" in supported,
        supports_tools=tool_support_state == "supported",
        supports_vision="image" in input_modalities,
        tool_support_state=tool_support_state,
        supported_parameters=supported_parameters,
        metadata_source="provider",
    )


class ModelCatalog:
    """In-memory cache of model metadata fetched from provider API.

    Priority chain for max_tokens:
      1. User config override (>0)
      2. Provider-qualified API-fetched catalog value
      3. Static fallback table
      4. DEFAULT_MAX_TOKENS (16384)
      -> then clamp to min(value, context_window)
    """

    def __init__(self) -> None:
        self._models: dict[str, ModelInfo] = {}
        self._provider_models: dict[tuple[str, str, str], ModelInfo] = {}

    def __len__(self) -> int:
        return len(self._models) + len(self._provider_models)

    def _store_model(
        self,
        info: ModelInfo,
        *,
        provider_name: str,
        base_url: str,
        bare: bool,
    ) -> None:
        provider_id = provider_name.strip().lower()
        if provider_id or base_url:
            self._provider_models[_provider_model_key(provider_id, base_url, info.model_id)] = info
        if bare:
            self._models[info.model_id] = info

    def _populate_from_data(self, models: list[dict]) -> None:
        """Parse a list of OpenRouter model dicts into ModelInfo entries."""
        self.add_models("openrouter", "", models)

    def add_models(self, provider_name: str, base_url: str, models: list[dict]) -> None:
        """Add provider-scoped model metadata rows."""
        provider_id = provider_name.strip().lower()
        for row in models:
            info = model_info_from_openai_compat_row(row, provider_id or provider_name)
            if info is None:
                continue
            self._store_model(
                info,
                provider_name=provider_id,
                base_url=base_url,
                bare=provider_id == "openrouter",
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
        info = self.get(model_id, provider_name=provider_name, base_url=base_url)
        if provider_id == "openai_compatible":
            tool_support_state = info.tool_support_state if info else "unknown"
            return ModelCapabilities(
                supports_reasoning=False,
                supports_tools=info.supports_tools if info else True,
                supports_vision=info.supports_vision if info else False,
                tool_support_state=tool_support_state,
                reasoning_format="none",
            )
        if info and info.supports_reasoning:
            return ModelCapabilities(
                supports_reasoning=True,
                supports_tools=info.supports_tools,
                supports_vision=info.supports_vision,
                tool_support_state=info.tool_support_state,
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
        if (
            provider_spec
            and provider_spec.backend == "openai_compat"
            and provider_id not in {"openai", "openrouter"}
        ):
            tool_support_state = info.tool_support_state if info else "unknown"
            return ModelCapabilities(
                supports_tools=info.supports_tools if info else False,
                supports_vision=info.supports_vision if info else False,
                tool_support_state=tool_support_state,
            )
        return ModelCapabilities(
            supports_tools=info.supports_tools if info else True,
            supports_vision=info.supports_vision if info else False,
            tool_support_state=info.tool_support_state if info else "supported",
        )

    async def fetch_openrouter(self, api_key: str, base_url: str, proxy: str = "") -> None:
        """Fetch model metadata from OpenRouter's /models endpoint."""
        url = f"{base_url.rstrip('/')}/v1/models"
        headers = {
            "Authorization": f"Bearer {clean_header_secret(api_key, label='OpenRouter API key')}"
        }
        headers.update(openrouter_app_headers(base_url))
        async with httpx.AsyncClient(
            timeout=10.0,
            trust_env=_trust_env(),
            proxy=proxy or None,
        ) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            self.add_models("openrouter", base_url, data.get("data", []))

    async def fetch_openai_compatible(
        self,
        *,
        provider_name: str,
        base_url: str,
        api_key: str = "",
        proxy: str = "",
        timeout: float = 5.0,
    ) -> None:
        """Fetch model metadata from an OpenAI-compatible /models endpoint."""
        headers: dict[str, str] = {}
        effective_key = clean_header_secret(api_key, label="LLM API key")
        if effective_key:
            headers["Authorization"] = f"Bearer {effective_key}"
        async with httpx.AsyncClient(
            timeout=timeout,
            trust_env=_trust_env(),
            proxy=proxy or None,
        ) as client:
            resp = await client.get(_models_url(base_url), headers=headers)
            resp.raise_for_status()
            data = resp.json()
            self.add_models(provider_name, base_url, data.get("data", []))

    def set_tool_probe_result(
        self,
        *,
        provider_name: str,
        base_url: str,
        model_id: str,
        supports_tools: bool,
    ) -> None:
        provider_id = provider_name.strip().lower()
        existing = self.get(model_id, provider_name=provider_id, base_url=base_url)
        if existing is not None:
            info = existing.model_copy(
                update={
                    "supports_tools": supports_tools,
                    "supported_parameters": ("tools",) if supports_tools else (),
                    "tool_support_state": "supported" if supports_tools else "unsupported",
                    "metadata_source": "tool_probe",
                }
            )
        else:
            info = ModelInfo(
                provider=provider_id,
                model_id=model_id,
                display_name=model_id,
                supports_tools=supports_tools,
                supported_parameters=("tools",) if supports_tools else (),
                tool_support_state="supported" if supports_tools else "unsupported",
                metadata_source="tool_probe",
            )
        self._store_model(
            info,
            provider_name=provider_id,
            base_url=base_url,
            bare=False,
        )

    async def probe_openai_compatible_tools(
        self,
        *,
        provider_name: str,
        base_url: str,
        model_id: str,
        api_key: str = "",
        proxy: str = "",
        timeout: float = 5.0,
        tool_probe_mode: str = "required",
    ) -> bool | None:
        headers: dict[str, str] = {}
        effective_key = clean_header_secret(api_key, label="LLM API key")
        if effective_key:
            headers["Authorization"] = f"Bearer {effective_key}"
        payload = {
            "model": model_id,
            "messages": [{"role": "user", "content": "Call the ping tool."}],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "ping",
                        "description": "Return an empty ping result.",
                        "parameters": {"type": "object", "properties": {}, "required": []},
                    },
                }
            ],
            "tool_choice": _normalize_tool_probe_mode(tool_probe_mode),
            "max_tokens": 16,
            "temperature": 0,
            "stream": False,
        }
        try:
            async with httpx.AsyncClient(
                timeout=timeout,
                trust_env=_trust_env(),
                proxy=proxy or None,
            ) as client:
                resp = await client.post(
                    _chat_completions_url(base_url),
                    headers=headers,
                    json=payload,
                )
                if resp.status_code in {400, 422}:
                    body = str(getattr(resp, "text", "") or "").lower()
                    if "tool" in body or "function" in body or "tool_choice" in body:
                        self.set_tool_probe_result(
                            provider_name=provider_name,
                            base_url=base_url,
                            model_id=model_id,
                            supports_tools=False,
                        )
                        return False
                resp.raise_for_status()
                data = resp.json()
        except Exception:  # noqa: BLE001 - probe is best-effort
            return None

        choices = data.get("choices", []) if isinstance(data, dict) else []
        accepted_tools = False
        if choices and isinstance(choices[0], dict):
            message = choices[0].get("message") or {}
            if isinstance(message, dict):
                accepted_tools = bool(message.get("tool_calls"))
        if not accepted_tools:
            # A 200 without tool_calls only proves the endpoint accepted the
            # tools payload; some endpoints (e.g. Inception diffusion models)
            # do not enforce tool_choice=required yet call tools fine in real
            # turns. Keep the capability unknown rather than persisting an
            # unsupported verdict; explicit rejection is the 400/422 branch.
            return None
        self.set_tool_probe_result(
            provider_name=provider_name,
            base_url=base_url,
            model_id=model_id,
            supports_tools=True,
        )
        return True

    def get(
        self,
        model_id: str,
        provider_name: str = "",
        base_url: str = "",
    ) -> ModelInfo | None:
        provider_id = provider_name.strip().lower()
        if provider_id or base_url:
            scoped = self._provider_models.get(_provider_model_key(provider_id, base_url, model_id))
            if scoped is not None:
                return scoped
            if provider_id == "openai_compatible":
                return None
        return self._models.get(model_id)

    def resolve_max_tokens(
        self,
        model_id: str,
        user_override: int = 0,
        provider_name: str = "",
        base_url: str = "",
    ) -> int:
        """Resolve max_tokens: user > catalog > static fallback > default, then clamp."""
        context_window = self.resolve_context_window(
            model_id,
            provider_name=provider_name,
            base_url=base_url,
        )
        info = self.get(model_id, provider_name=provider_name, base_url=base_url)

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

    def resolve_context_window(
        self,
        model_id: str,
        provider_name: str = "",
        base_url: str = "",
    ) -> int:
        """Resolve context window: catalog > static fallback > default."""
        info = self.get(model_id, provider_name=provider_name, base_url=base_url)
        if info and info.context_window > 0:
            return info.context_window
        if model_id in _STATIC_FALLBACK:
            return _STATIC_FALLBACK[model_id][1]
        return DEFAULT_CONTEXT_WINDOW
