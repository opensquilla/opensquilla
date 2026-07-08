"""Per-provider dialect policy for the OpenAI-compatible backend.

Twenty-plus providers share ``OpenAIProvider``. What tells them apart is not
code but *data*: which token-limit field the upstream accepts, which JSON
Schema keywords it rejects, whether it leaks MiniMax's plain-text tool
protocol, whether its billed cost can be trusted, which models need explicit
thinking toggles. ``OpenAICompatPolicy`` is that data — one frozen record per
``provider_kind``, consumed by the request builder and stream loop instead of
``provider_kind == ...`` branches scattered through them.

The registry attaches a policy to every ``ProviderSpec``; constructing an
``OpenAIProvider`` without one falls back to the kind-keyed default so
direct construction (tests, tooling) behaves identically to the registry
path.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OpenAICompatPolicy:
    """Declarative quirks of one OpenAI-compatible provider dialect."""

    # Human-readable name used in error messages ("OpenRouter chat request
    # failed (HTTP 400): ...").
    display_name: str = "Provider"

    # Host marker gating quirks that only apply to the provider's official
    # endpoint (an OpenAI-compatible re-host of the same models usually does
    # not share them).
    official_host: str = ""

    # Models that take ``max_completion_tokens`` instead of ``max_tokens``
    # (matched on the model basename, official host only).
    max_completion_tokens_model_prefixes: tuple[str, ...] = ()

    # Models whose sampling is fixed upstream: a non-default temperature is
    # dropped rather than rejected by the API.
    fixed_sampling_model_prefixes: tuple[str, ...] = ()

    # Models that reject a temperature while extended thinking is active
    # (official host only).
    omit_temperature_when_thinking_model_prefixes: tuple[str, ...] = ()

    # JSON Schema keywords the upstream rejects in tool definitions.
    tool_schema_unsupported_keywords: frozenset[str] = frozenset()

    # Whether the upstream is known to leak MiniMax's plain-text tool-call
    # protocol, enabling last-resort text-to-tool-call synthesis.
    text_tool_synthesis: bool = False

    # Whether usage.cost from this upstream is authoritative billing data.
    trust_billed_cost: bool = False

    # OpenRouter-family request extras.
    sends_usage_include: bool = False
    supports_provider_routing_pin: bool = False
    supports_explicit_prompt_cache: bool = False
    anthropic_top_level_cache: bool = False
    stream_timeout_fallback: bool = False
    log_payload_cache_shape: bool = False

    # Gateway proxies with their own routing (LiteLLM): pin the requested
    # model by disabling the gateway's cross-model fallbacks per request, so
    # SquillaRouter stays the single routing authority.
    sends_disable_fallbacks: bool = False

    # Response headers that report which deployment actually served the
    # request (logged for attribution; a routing deviation must be visible).
    attribution_response_headers: tuple[str, ...] = ()

    # Reasoning continuity: replay assistant reasoning_content when the model
    # capabilities declare this reasoning format.
    replay_reasoning_format: str = ""

    # Reasoning format assumed when no model capabilities are available.
    default_reasoning_format: str = ""

    # Models that need an explicit thinking enable/disable payload even when
    # no capability profile is available (exact ids, lowercase).
    thinking_toggle_model_ids: frozenset[str] = frozenset()

    # Models that require reasoning_content on every assistant message —
    # including an empty string when there is none (exact ids, lowercase).
    require_reasoning_content_model_ids: frozenset[str] = frozenset()

    # Models that stream reasoning by default and need it explicitly disabled
    # when thinking is off (exact ids, lowercase).
    disable_reasoning_by_default_models: frozenset[str] = frozenset()


_ARK_UNSUPPORTED_TOOL_SCHEMA_KEYWORDS = frozenset(
    {
        "minLength",
        "maxLength",
        "minItems",
        "maxItems",
        "minContains",
        "maxContains",
    }
)

_DEEPSEEK_V4_MODEL_IDS = frozenset({"deepseek-v4-flash", "deepseek-v4-pro"})

# TokenHub's hy3 family documents interleaved thinking: assistant turns must
# carry reasoning_content back (an empty string when there is none), or the
# reasoning context is lost across tool-call rounds.
_TOKENHUB_HY3_MODEL_IDS = frozenset({"hy3", "hy3-preview"})

# OpenRouter's reasoning controls are model/provider-specific: GLM can be
# stabilized by explicitly disabling reasoning when OpenSquilla has not
# requested thinking, while MiniMax reasoning endpoints reject that payload.
_OPENROUTER_DISABLE_REASONING_MODELS = frozenset(
    {
        "z-ai/glm-4.5",
        "z-ai/glm-4.5-air",
        "z-ai/glm-5",
        "z-ai/glm-5.1",
        "z-ai/glm-5.2",
    }
)


_POLICIES_BY_KIND: dict[str, OpenAICompatPolicy] = {
    "openai": OpenAICompatPolicy(
        display_name="OpenAI",
        official_host="api.openai.com",
        max_completion_tokens_model_prefixes=("gpt-5", "o1", "o3", "o4"),
        omit_temperature_when_thinking_model_prefixes=("gpt-5.4", "gpt-5.5"),
    ),
    "openrouter": OpenAICompatPolicy(
        display_name="OpenRouter",
        text_tool_synthesis=True,
        trust_billed_cost=True,
        sends_usage_include=True,
        supports_provider_routing_pin=True,
        supports_explicit_prompt_cache=True,
        anthropic_top_level_cache=True,
        stream_timeout_fallback=True,
        log_payload_cache_shape=True,
        replay_reasoning_format="openrouter",
        disable_reasoning_by_default_models=_OPENROUTER_DISABLE_REASONING_MODELS,
    ),
    "azure": OpenAICompatPolicy(display_name="Azure OpenAI"),
    "deepseek": OpenAICompatPolicy(
        display_name="DeepSeek",
        default_reasoning_format="deepseek",
        # Reasoning replay is gated on the exact V4 ids (below), not on the
        # capability format: non-V4 DeepSeek models must not get replay.
        thinking_toggle_model_ids=_DEEPSEEK_V4_MODEL_IDS,
        require_reasoning_content_model_ids=_DEEPSEEK_V4_MODEL_IDS,
    ),
    "gemini": OpenAICompatPolicy(display_name="Gemini"),
    "dashscope": OpenAICompatPolicy(
        display_name="DashScope",
        text_tool_synthesis=True,
        supports_explicit_prompt_cache=True,
        stream_timeout_fallback=True,
    ),
    "bailian_coding": OpenAICompatPolicy(display_name="Bailian Coding"),
    "moonshot": OpenAICompatPolicy(
        display_name="Moonshot",
        fixed_sampling_model_prefixes=("kimi-k2.5", "kimi-k2.6"),
    ),
    "minimax": OpenAICompatPolicy(
        display_name="MiniMax",
        text_tool_synthesis=True,
    ),
    "mistral": OpenAICompatPolicy(display_name="Mistral"),
    "groq": OpenAICompatPolicy(display_name="Groq"),
    "zhipu": OpenAICompatPolicy(display_name="Zhipu"),
    "qianfan": OpenAICompatPolicy(display_name="Qianfan"),
    "siliconflow": OpenAICompatPolicy(display_name="SiliconFlow"),
    "aihubmix": OpenAICompatPolicy(display_name="AiHubMix"),
    "volcengine": OpenAICompatPolicy(
        display_name="Volcengine",
        tool_schema_unsupported_keywords=_ARK_UNSUPPORTED_TOOL_SCHEMA_KEYWORDS,
    ),
    "byteplus": OpenAICompatPolicy(
        display_name="BytePlus",
        tool_schema_unsupported_keywords=_ARK_UNSUPPORTED_TOOL_SCHEMA_KEYWORDS,
    ),
    "tencent_tokenhub": OpenAICompatPolicy(
        display_name="Tencent TokenHub",
        replay_reasoning_format="tencent_tokenhub",
        require_reasoning_content_model_ids=_TOKENHUB_HY3_MODEL_IDS,
    ),
    "lm_studio": OpenAICompatPolicy(display_name="LM Studio"),
    "ovms": OpenAICompatPolicy(display_name="OpenVINO Model Server"),
    "litellm_proxy": OpenAICompatPolicy(
        display_name="LiteLLM Proxy",
        sends_disable_fallbacks=True,
        attribution_response_headers=(
            "x-litellm-model-id",
            "x-litellm-model-api-base",
            "x-litellm-model-group",
            "x-litellm-attempted-retries",
            "x-litellm-attempted-fallbacks",
        ),
    ),
}

_DEFAULT_POLICY = OpenAICompatPolicy()


def compat_policy_for_kind(provider_kind: str) -> OpenAICompatPolicy:
    """Return the dialect policy for a provider kind (default when unknown)."""
    return _POLICIES_BY_KIND.get(provider_kind, _DEFAULT_POLICY)


def known_policy_kinds() -> frozenset[str]:
    """Provider kinds with an explicit policy (for registry sync tests)."""
    return frozenset(_POLICIES_BY_KIND)
