"""Parity proof for the spec-carried ProviderContextProfile extraction.

Every expected value below is a literal transcribed from the pre-extraction
``provider_context_capabilities`` if-ladder (openrouter / anthropic / gemini /
openai_responses / openai branches plus the default). The sweep covers every
registered provider id at its default base URL, the host-guarded cases that
deliberately stayed code (gemini-by-host, openai-by-host, openai-custom-host),
and the OpenRouter per-model-prefix prompt-cache table. Any assertion change
here means the extraction changed behavior and must be reviewed as such.
"""

from __future__ import annotations

import pytest

from opensquilla.provider.context_capabilities import (
    NativeCompactionSupport,
    PromptCacheSupport,
    ProviderContextCapabilities,
    provider_context_capabilities,
    supports_openrouter_explicit_prompt_cache,
)
from opensquilla.provider.registry import get_provider_spec, list_provider_names

# Neutral model id: matches no OpenRouter prefix and no gemini flash/pro
# marker, so it exercises each branch's fallback shape.
_SWEEP_MODEL = "parity-sweep-model"


def _default_caps(provider: str, model: str = _SWEEP_MODEL) -> ProviderContextCapabilities:
    return ProviderContextCapabilities(provider=provider, model=model)


def _anthropic_caps(provider: str, model: str = _SWEEP_MODEL) -> ProviderContextCapabilities:
    return ProviderContextCapabilities(
        provider=provider,
        model=model,
        prompt_cache=PromptCacheSupport.EXPLICIT,
        native_compaction=NativeCompactionSupport.NONE,
        supports_cache_breakpoints=True,
        state_portable_across_providers=False,
    )


def _gemini_caps(
    provider: str,
    model: str = _SWEEP_MODEL,
    min_cache_tokens: int | None = None,
) -> ProviderContextCapabilities:
    return ProviderContextCapabilities(
        provider=provider,
        model=model,
        prompt_cache=PromptCacheSupport.IMPLICIT,
        native_compaction=NativeCompactionSupport.NONE,
        min_cache_tokens=min_cache_tokens,
        state_portable_across_providers=False,
    )


def _responses_caps(provider: str, model: str = _SWEEP_MODEL) -> ProviderContextCapabilities:
    return ProviderContextCapabilities(
        provider=provider,
        model=model,
        prompt_cache=PromptCacheSupport.AUTOMATIC,
        native_compaction=NativeCompactionSupport.STANDALONE,
        native_compaction_state_kind="openai_responses_compacted_window",
        state_portable_across_providers=False,
    )


def _openai_host_caps(provider: str, model: str = _SWEEP_MODEL) -> ProviderContextCapabilities:
    return ProviderContextCapabilities(
        provider=provider,
        model=model,
        prompt_cache=PromptCacheSupport.AUTOMATIC,
        state_portable_across_providers=False,
    )


def _openrouter_caps(model: str, prompt_cache: PromptCacheSupport) -> ProviderContextCapabilities:
    return ProviderContextCapabilities(
        provider="openrouter",
        model=model,
        prompt_cache=prompt_cache,
        supports_cache_breakpoints=prompt_cache == PromptCacheSupport.EXPLICIT,
        state_portable_across_providers=False,
    )


# Provider ids whose pre-extraction output differed from the all-defaults
# capability record when called with the spec's default base URL.
_EXPECTED_BY_PROVIDER_ID: dict[str, ProviderContextCapabilities] = {
    "anthropic": _anthropic_caps("anthropic"),
    "gemini": _gemini_caps("gemini"),
    "openai": _openai_host_caps("openai"),  # default base URL is api.openai.com
    "openai_responses": _responses_caps("openai_responses"),
    "openrouter": _openrouter_caps(_SWEEP_MODEL, PromptCacheSupport.IMPLICIT),
}


@pytest.mark.parametrize("provider_id", list_provider_names())
def test_registered_provider_matches_pre_extraction_output(provider_id: str) -> None:
    spec = get_provider_spec(provider_id)
    caps = provider_context_capabilities(
        provider_kind=provider_id,
        model=_SWEEP_MODEL,
        base_url=spec.default_base_url,
    )
    expected = _EXPECTED_BY_PROVIDER_ID.get(provider_id, _default_caps(provider_id))
    assert caps == expected


_TARGETED_CASES: list[tuple[str, str, str, str, ProviderContextCapabilities]] = [
    # OpenRouter model-prefix table (per-model prompt-cache resolution).
    (
        "openrouter-anthropic-prefix",
        "openrouter",
        "anthropic/claude-sonnet-4-6",
        "https://openrouter.ai/api/v1",
        _openrouter_caps("anthropic/claude-sonnet-4-6", PromptCacheSupport.EXPLICIT),
    ),
    (
        "openrouter-google-prefix",
        "openrouter",
        "google/gemini-2.5-pro",
        "https://openrouter.ai/api/v1",
        _openrouter_caps("google/gemini-2.5-pro", PromptCacheSupport.EXPLICIT),
    ),
    (
        "openrouter-deepseek-prefix",
        "openrouter",
        "deepseek/deepseek-v4-pro",
        "https://openrouter.ai/api/v1",
        _openrouter_caps("deepseek/deepseek-v4-pro", PromptCacheSupport.EXPLICIT),
    ),
    (
        "openrouter-x-ai-prefix",
        "openrouter",
        "x-ai/grok-4",
        "https://openrouter.ai/api/v1",
        _openrouter_caps("x-ai/grok-4", PromptCacheSupport.EXPLICIT),
    ),
    (
        "openrouter-z-ai-prefix",
        "openrouter",
        "z-ai/glm-5.1",
        "https://openrouter.ai/api/v1",
        _openrouter_caps("z-ai/glm-5.1", PromptCacheSupport.IMPLICIT),
    ),
    (
        "openrouter-unmatched-prefix",
        "openrouter",
        "qwen/qwen3-max",
        "https://openrouter.ai/api/v1",
        _openrouter_caps("qwen/qwen3-max", PromptCacheSupport.IMPLICIT),
    ),
    # Whitespace/case normalization flows through the new lookup path.
    (
        "openrouter-normalized-input",
        "  OpenRouter  ",
        "Anthropic/Claude-Sonnet-4-6",
        "",
        _openrouter_caps("Anthropic/Claude-Sonnet-4-6", PromptCacheSupport.EXPLICIT),
    ),
    # Anthropic is provider-keyed: a custom base URL keeps the profile.
    (
        "anthropic-custom-host",
        "anthropic",
        "claude-opus-4-6",
        "https://anthropic-proxy.example.com",
        _anthropic_caps("anthropic", "claude-opus-4-6"),
    ),
    # Gemini by provider kind: flash/pro minimum cache-token ladder.
    (
        "gemini-flash-min-tokens",
        "gemini",
        "gemini-2.5-flash",
        "https://generativelanguage.googleapis.com/v1beta/openai",
        _gemini_caps("gemini", "gemini-2.5-flash", min_cache_tokens=1024),
    ),
    (
        "gemini-pro-min-tokens",
        "gemini",
        "gemini-2.5-pro",
        "https://generativelanguage.googleapis.com/v1beta/openai",
        _gemini_caps("gemini", "gemini-2.5-pro", min_cache_tokens=4096),
    ),
    (
        "gemini-kind-custom-host",
        "gemini",
        "gemini-2.5-flash",
        "https://gemini-proxy.example.com/v1",
        _gemini_caps("gemini", "gemini-2.5-flash", min_cache_tokens=1024),
    ),
    # Gemini by host: a non-gemini kind pointed at generativelanguage still
    # resolves the gemini cache behavior (host guard stayed code).
    (
        "gemini-by-host-openai-kind",
        "openai",
        "gemini-2.5-flash",
        "https://generativelanguage.googleapis.com/v1beta/openai",
        _gemini_caps("openai", "gemini-2.5-flash", min_cache_tokens=1024),
    ),
    (
        "gemini-by-host-azure-kind",
        "azure",
        "gemini-2.5-pro",
        "https://generativelanguage.googleapis.com/v1beta/openai",
        _gemini_caps("azure", "gemini-2.5-pro", min_cache_tokens=4096),
    ),
    # OpenAI host guard: automatic caching only on the official host.
    (
        "openai-by-host",
        "openai",
        "gpt-5.4",
        "https://api.openai.com/v1",
        _openai_host_caps("openai", "gpt-5.4"),
    ),
    (
        "openai-custom-host",
        "openai",
        "gpt-5.4",
        "https://openai-compat.example.com/v1",
        _default_caps("openai", "gpt-5.4"),
    ),
    (
        "openai-empty-base-url",
        "openai",
        "gpt-5.4",
        "",
        _default_caps("openai", "gpt-5.4"),
    ),
    # openai_responses is provider-keyed: no host requirement.
    (
        "openai-responses-no-base-url",
        "openai_responses",
        "gpt-5.5",
        "",
        _responses_caps("openai_responses", "gpt-5.5"),
    ),
    # Anthropic-shaped MiniMax kinds never had the anthropic cache profile.
    (
        "minimax-kind-stays-default",
        "minimax",
        "minimax-m2.5",
        "https://api.minimaxi.com/anthropic",
        _default_caps("minimax", "minimax-m2.5"),
    ),
    # Unregistered kinds fall through to the all-defaults record.
    (
        "unknown-kind",
        "totally-unknown-kind",
        _SWEEP_MODEL,
        "https://example.com/v1",
        _default_caps("totally-unknown-kind"),
    ),
]


@pytest.mark.parametrize(
    ("provider_kind", "model", "base_url", "expected"),
    [case[1:] for case in _TARGETED_CASES],
    ids=[case[0] for case in _TARGETED_CASES],
)
def test_host_guard_and_prefix_cases_match_pre_extraction_output(
    provider_kind: str,
    model: str,
    base_url: str,
    expected: ProviderContextCapabilities,
) -> None:
    caps = provider_context_capabilities(
        provider_kind=provider_kind, model=model, base_url=base_url
    )
    assert caps == expected


def test_openrouter_explicit_prompt_cache_wrapper_unchanged() -> None:
    assert supports_openrouter_explicit_prompt_cache("anthropic/claude-sonnet-4-6") is True
    assert supports_openrouter_explicit_prompt_cache("x-ai/grok-4") is True
    assert supports_openrouter_explicit_prompt_cache("z-ai/glm-5.1") is False
    assert supports_openrouter_explicit_prompt_cache("qwen/qwen3-max") is False
