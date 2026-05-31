from __future__ import annotations

from opensquilla.provider.context_capabilities import (
    NativeCompactionSupport,
    PromptCacheSupport,
    provider_context_capabilities,
    provider_state_continuity_diagnostic,
)
from opensquilla.provider.model_catalog import ModelCatalog


def test_deepseek_provider_profile_enables_deepseek_reasoning_format() -> None:
    caps = ModelCatalog().get_capabilities(
        "deepseek-chat",
        provider_name="deepseek",
        base_url="https://api.deepseek.com",
    )

    assert caps.supports_reasoning is True
    assert caps.supports_tools is True
    assert caps.reasoning_format == "deepseek"


def test_gemini_reasoning_model_uses_gemini_reasoning_format() -> None:
    caps = ModelCatalog().get_capabilities(
        "gemini-2.5-flash",
        provider_name="gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
    )

    assert caps.supports_reasoning is True
    assert caps.reasoning_format == "gemini"


def test_direct_openai_gpt_5_models_use_openai_reasoning_effort_format() -> None:
    catalog = ModelCatalog()

    for model in ("gpt-5.4-nano", "gpt-5.4-mini", "gpt-5.5"):
        caps = catalog.get_capabilities(
            model,
            provider_name="openai",
            base_url="https://api.openai.com/v1",
        )

        assert caps.supports_reasoning is True
        assert caps.supports_tools is True
        assert caps.reasoning_format == "openai"


def test_zai_glm5_models_use_zai_reasoning_format() -> None:
    catalog = ModelCatalog()

    for model in ("glm-4.7-flashx", "glm-5", "glm-5.1"):
        caps = catalog.get_capabilities(
            model,
            provider_name="zhipu",
            base_url="https://open.bigmodel.cn/api/paas/v4",
        )

        assert caps.supports_reasoning is True
        assert caps.supports_tools is True
        assert caps.reasoning_format == "zai"


def test_dashscope_qwen_thinking_models_use_dashscope_reasoning_format() -> None:
    catalog = ModelCatalog()

    for model in ("qwen3.6-flash", "qwen3.6-plus", "qwen3-max"):
        caps = catalog.get_capabilities(
            model,
            provider_name="dashscope",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )

        assert caps.supports_reasoning is True
        assert caps.supports_tools is True
        assert caps.reasoning_format == "dashscope"


def test_moonshot_distinguishes_kimi_thinking_from_moonshot_v1() -> None:
    catalog = ModelCatalog()

    kimi_caps = catalog.get_capabilities(
        "kimi-k2.5",
        provider_name="moonshot",
        base_url="https://api.moonshot.cn/v1",
    )
    v1_caps = catalog.get_capabilities(
        "moonshot-v1-128k",
        provider_name="moonshot",
        base_url="https://api.moonshot.cn/v1",
    )

    assert kimi_caps.supports_reasoning is True
    assert kimi_caps.reasoning_format == "moonshot"
    assert v1_caps.supports_reasoning is False
    assert v1_caps.reasoning_format == "none"


def test_volcengine_doubao_thinking_models_use_volcengine_reasoning_format() -> None:
    catalog = ModelCatalog()

    thinking_caps = catalog.get_capabilities(
        "doubao-seed-1-6-thinking-250715",
        provider_name="volcengine",
        base_url="https://ark.cn-beijing.volces.com/api/v3",
    )
    plain_caps = catalog.get_capabilities(
        "doubao-seed-1-6-251015",
        provider_name="volcengine",
        base_url="https://ark.cn-beijing.volces.com/api/v3",
    )

    assert thinking_caps.supports_reasoning is True
    assert thinking_caps.reasoning_format == "volcengine"
    assert plain_caps.supports_reasoning is False
    assert plain_caps.reasoning_format == "none"


def test_unknown_compatible_model_degrades_to_tools_only() -> None:
    caps = ModelCatalog().get_capabilities(
        "unknown-model",
        provider_name="moonshot",
        base_url="https://api.moonshot.ai/v1",
    )

    assert caps.supports_reasoning is False
    assert caps.supports_tools is True
    assert caps.reasoning_format == "none"


def test_openrouter_context_capability_profile_centralizes_prompt_cache_decision() -> None:
    deepseek = provider_context_capabilities(
        provider_kind="openrouter",
        model="deepseek/deepseek-v4-pro",
    )
    zai = provider_context_capabilities(
        provider_kind="openrouter",
        model="z-ai/glm-5.1",
    )

    assert deepseek.prompt_cache == PromptCacheSupport.EXPLICIT
    assert deepseek.supports_cache_breakpoints is True
    assert deepseek.native_compaction == NativeCompactionSupport.NONE
    assert deepseek.state_portable_across_providers is False

    assert zai.prompt_cache == PromptCacheSupport.IMPLICIT
    assert zai.supports_cache_breakpoints is False
    assert zai.native_compaction == NativeCompactionSupport.NONE


def test_anthropic_context_capability_does_not_claim_native_compaction() -> None:
    caps = provider_context_capabilities(
        provider_kind="anthropic",
        model="claude-opus-4-7",
    )

    assert caps.native_compaction == NativeCompactionSupport.NONE
    assert caps.native_compaction_state_kind is None
    assert caps.supports_cache_breakpoints is True


def test_anthropic_context_capability_keeps_other_models_on_generic_compaction() -> None:
    caps = provider_context_capabilities(
        provider_kind="anthropic",
        model="claude-3-5-sonnet-20241022",
    )

    assert caps.native_compaction == NativeCompactionSupport.NONE
    assert caps.native_compaction_state_kind is None
    assert caps.supports_cache_breakpoints is True


def test_openai_responses_context_capability_declares_standalone_compaction() -> None:
    caps = provider_context_capabilities(
        provider_kind="openai_responses",
        model="gpt-5.5",
        base_url="https://api.openai.com/v1",
    )

    assert caps.prompt_cache == PromptCacheSupport.AUTOMATIC
    assert caps.native_compaction == NativeCompactionSupport.STANDALONE
    assert caps.native_compaction_state_kind == "openai_responses_compacted_window"
    assert caps.state_portable_across_providers is False


def test_context_capability_profile_exposes_cache_and_native_state_fields() -> None:
    caps = provider_context_capabilities(
        provider_kind="gemini",
        model="gemini-2.5-flash",
    )

    assert caps.prompt_cache == PromptCacheSupport.IMPLICIT
    assert caps.native_compaction == NativeCompactionSupport.NONE
    assert caps.supports_cache_breakpoints is False
    assert caps.state_portable_across_providers is False
    assert caps.min_cache_tokens == 1024
    assert caps.cache_ttl_options == ()


def test_gemini_context_capability_treats_cached_content_as_cache_not_compaction() -> None:
    caps = provider_context_capabilities(
        provider_kind="gemini",
        model="gemini-2.5-pro",
    )

    assert caps.prompt_cache == PromptCacheSupport.IMPLICIT
    assert caps.native_compaction == NativeCompactionSupport.NONE
    assert caps.native_compaction_state_kind is None
    assert caps.min_cache_tokens == 4096


def test_provider_state_continuity_diagnostic_reports_safe_actions() -> None:
    keep = provider_state_continuity_diagnostic(
        context_states=[
            {
                "provider": "anthropic",
                "model": "claude-sonnet-4-6",
                "state_kind": "anthropic_compaction_block",
                "valid": True,
                "portable": False,
            }
        ],
        candidate_provider="anthropic",
        candidate_model="claude-opus-4-7",
    )
    fallback = provider_state_continuity_diagnostic(
        context_states=[
            {
                "provider": "anthropic",
                "model": "claude-sonnet-4-6",
                "state_kind": "anthropic_compaction_block",
                "valid": True,
                "portable": False,
            },
            {
                "provider": "portable",
                "model": "",
                "state_kind": "structured_summary_v1",
                "valid": True,
                "portable": True,
            },
        ],
        candidate_provider="openrouter",
        candidate_model="deepseek/deepseek-v4-flash",
    )

    assert keep.decision == "keep_provider"
    assert keep.provider_state_loss_risk is False
    assert fallback.decision == "use_portable_fallback"
    assert fallback.provider_state_loss_risk is True


def test_provider_state_continuity_diagnostic_prefers_latest_matching_native_state() -> None:
    diagnostic = provider_state_continuity_diagnostic(
        context_states=[
            {
                "provider": "anthropic",
                "model": "claude-sonnet-4-6",
                "state_kind": "anthropic_compaction_block",
                "created_at": 100,
                "valid": True,
                "portable": False,
            },
            {
                "provider": "openai_responses",
                "model": "gpt-5.5",
                "state_kind": "openai_responses_compacted_window",
                "created_at": 200,
                "valid": True,
                "portable": False,
            },
        ],
        candidate_provider="openai_responses",
        candidate_model="gpt-5.5",
    )

    assert diagnostic.decision == "keep_provider"
    assert diagnostic.provider_state_loss_risk is False
    assert diagnostic.active_state_provider == "openai_responses"
    assert diagnostic.active_state_kind == "openai_responses_compacted_window"


def test_provider_state_continuity_diagnostic_ignores_expired_native_state() -> None:
    diagnostic = provider_state_continuity_diagnostic(
        context_states=[
            {
                "provider": "anthropic",
                "model": "claude-sonnet-4-6",
                "state_kind": "anthropic_compaction_block",
                "created_at": 100,
                "expires_at": 150,
                "valid": True,
                "portable": False,
            },
            {
                "provider": "portable",
                "state_kind": "structured_summary_v1",
                "created_at": 90,
                "valid": True,
                "portable": True,
            },
        ],
        candidate_provider="openrouter",
        candidate_model="deepseek/deepseek-v4-flash",
        now_ms=200,
    )

    assert diagnostic.decision == "use_portable_fallback"
    assert diagnostic.provider_state_loss_risk is False
    assert diagnostic.active_state_kind is None
    assert diagnostic.portable_fallback_available is True
