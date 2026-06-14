from __future__ import annotations

import pytest

from opensquilla.provider.anthropic import AnthropicProvider
from opensquilla.provider.openai import OpenAIProvider
from opensquilla.provider.registry import get_provider_spec, list_provider_specs
from opensquilla.provider.selector import ProviderBuildError, ProviderConfig, _build_provider

MAINSTREAM_PROVIDER_LEVELS = {
    "openrouter": "compat_mock_verified",
    "openai": "compat_mock_verified",
    "inception": "live_verified",
    "anthropic": "native",
    "ollama": "native",
    "deepseek": "compat_mock_verified",
    "gemini": "compat_mock_verified",
    "mistral": "compat_mock_verified",
    "groq": "compat_mock_verified",
    "dashscope": "compat_mock_verified",
    "bailian_coding": "compat_configured",
    "moonshot": "compat_mock_verified",
    "zhipu": "compat_mock_verified",
    "siliconflow": "compat_mock_verified",
    "volcengine": "compat_mock_verified",
    "byteplus": "compat_mock_verified",
    "vllm": "compat_mock_verified",
    "lm_studio": "compat_mock_verified",
    "ovms": "compat_mock_verified",
    "qianfan": "compat_configured",
    "aihubmix": "compat_configured",
    "minimax": "compat_configured",
    "minimax_openai": "compat_configured",
    "minimax_cn": "compat_configured",
    "minimax_global": "compat_configured",
    "azure": "unsupported_for_A",
}


def test_mainstream_registry_exposes_support_levels() -> None:
    specs = {spec.provider_id: spec for spec in list_provider_specs()}

    for provider, support_level in MAINSTREAM_PROVIDER_LEVELS.items():
        assert specs[provider].support_level == support_level


@pytest.mark.parametrize(
    ("provider", "provider_kind"),
    [
        ("deepseek", "deepseek"),
        ("inception", "inception"),
        ("gemini", "gemini"),
        ("dashscope", "dashscope"),
        ("bailian_coding", "bailian_coding"),
        ("moonshot", "moonshot"),
        ("mistral", "mistral"),
        ("groq", "groq"),
        ("zhipu", "zhipu"),
        ("siliconflow", "siliconflow"),
        ("volcengine", "volcengine"),
        ("byteplus", "byteplus"),
        ("qianfan", "qianfan"),
        ("aihubmix", "aihubmix"),
        ("lm_studio", "lm_studio"),
        ("ovms", "ovms"),
    ],
)
def test_new_openai_compatible_profiles_have_vendor_provider_kind(
    provider: str,
    provider_kind: str,
) -> None:
    assert get_provider_spec(provider).provider_kind == provider_kind


@pytest.mark.parametrize(
    ("provider", "env_key", "base_url"),
    [
        ("deepseek", "DEEPSEEK_API_KEY", "https://api.deepseek.com"),
        ("inception", "INCEPTION_API_KEY", "https://api.inceptionlabs.ai/v1"),
        (
            "gemini",
            "GEMINI_API_KEY",
            "https://generativelanguage.googleapis.com/v1beta/openai",
        ),
        ("dashscope", "DASHSCOPE_API_KEY", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        (
            "bailian_coding",
            "BAILIAN_API_KEY",
            "https://coding-intl.dashscope.aliyuncs.com/v1",
        ),
        ("moonshot", "MOONSHOT_API_KEY", "https://api.moonshot.ai/v1"),
        ("mistral", "MISTRAL_API_KEY", "https://api.mistral.ai/v1"),
        ("groq", "GROQ_API_KEY", "https://api.groq.com/openai/v1"),
        ("zhipu", "ZAI_API_KEY", "https://open.bigmodel.cn/api/paas/v4"),
        ("siliconflow", "SILICONFLOW_API_KEY", "https://api.siliconflow.cn/v1"),
        ("volcengine", "VOLCENGINE_API_KEY", "https://ark.cn-beijing.volces.com/api/v3"),
        ("byteplus", "BYTEPLUS_API_KEY", "https://ark.ap-southeast.bytepluses.com/api/v3"),
        ("qianfan", "QIANFAN_API_KEY", "https://qianfan.baidubce.com/v2"),
        ("aihubmix", "AIHUBMIX_API_KEY", "https://aihubmix.com/v1"),
        ("lm_studio", "", "http://localhost:1234/v1"),
        ("ovms", "", "http://localhost:8000/v3"),
    ],
)
def test_openai_compatible_profiles_have_documented_config(
    provider: str,
    env_key: str,
    base_url: str,
) -> None:
    spec = get_provider_spec(provider)

    assert spec.backend == "openai_compat"
    assert spec.env_key == env_key
    assert spec.default_base_url == base_url
    expected_required = frozenset({"model"}) if not env_key else frozenset({"api_key", "model"})
    assert spec.required_fields == expected_required


def test_minimax_mainland_profile_uses_anthropic_compatible_endpoint() -> None:
    spec = get_provider_spec("minimax")

    assert spec.backend == "anthropic"
    assert spec.provider_kind == "minimax"
    assert spec.env_key == "MINIMAX_API_KEY"
    assert spec.default_base_url == "https://api.minimaxi.com/anthropic"
    assert spec.usage_shape == "anthropic"
    assert spec.failure_family == "anthropic"


def test_minimax_region_profiles_are_explicit_anthropic_compatible_endpoints() -> None:
    mainland = get_provider_spec("minimax_cn")
    global_ = get_provider_spec("minimax_global")

    assert mainland.backend == "anthropic"
    assert mainland.provider_kind == "minimax"
    assert mainland.env_key == "MINIMAX_CN_API_KEY"
    assert mainland.default_base_url == "https://api.minimaxi.com/anthropic"
    assert mainland.usage_shape == "anthropic"
    assert mainland.failure_family == "anthropic"

    assert global_.backend == "anthropic"
    assert global_.provider_kind == "minimax"
    assert global_.env_key == "MINIMAX_API_KEY"
    assert global_.default_base_url == "https://api.minimax.io/anthropic"
    assert global_.usage_shape == "anthropic"
    assert global_.failure_family == "anthropic"


@pytest.mark.parametrize(
    ("provider", "model"),
    [
        ("deepseek", "deepseek-chat"),
        ("inception", "mercury-2"),
        ("gemini", "gemini-2.5-flash"),
        ("dashscope", "qwen-plus"),
        ("bailian_coding", "kimi-k2.5"),
        ("moonshot", "kimi-k2.5"),
        ("mistral", "mistral-large-latest"),
        ("groq", "llama-3.3-70b-versatile"),
        ("zhipu", "glm-4.5"),
        ("siliconflow", "deepseek-ai/DeepSeek-V3"),
        ("volcengine", "ark-model-id"),
        ("byteplus", "ark-endpoint-id"),
        ("qianfan", "ernie-4.5-turbo-128k"),
        ("aihubmix", "openai/gpt-5-mini"),
        ("minimax_openai", "MiniMax-M2.7"),
        ("lm_studio", "local-model"),
        ("ovms", "llama3"),
    ],
)
def test_model_selector_builds_registered_openai_compatible_providers(
    provider: str,
    model: str,
) -> None:
    built = _build_provider(ProviderConfig(provider=provider, model=model, api_key="test-key"))

    assert isinstance(built, OpenAIProvider)


def test_model_selector_builds_minimax_mainland_anthropic_provider() -> None:
    built = _build_provider(
        ProviderConfig(provider="minimax", model="MiniMax-M2.7", api_key="test-key")
    )

    assert isinstance(built, AnthropicProvider)


def test_model_selector_builds_minimax_openai_compatible_provider() -> None:
    spec = get_provider_spec("minimax_openai")
    assert spec.backend == "openai_compat"
    assert spec.provider_kind == "minimax"
    assert spec.env_key == "MINIMAX_API_KEY"
    assert spec.default_base_url == "https://api.minimaxi.com/v1"

    built = _build_provider(
        ProviderConfig(provider="minimax_openai", model="MiniMax-M2.7", api_key="test-key")
    )

    assert isinstance(built, OpenAIProvider)


@pytest.mark.parametrize("provider", ["minimax_cn", "minimax_global"])
def test_model_selector_builds_explicit_minimax_region_anthropic_providers(
    provider: str,
) -> None:
    built = _build_provider(
        ProviderConfig(provider=provider, model="MiniMax-M2.7", api_key="test-key")
    )

    assert isinstance(built, AnthropicProvider)


def test_vllm_requires_explicit_base_url() -> None:
    with pytest.raises(ProviderBuildError, match="requires an explicit base_url"):
        _build_provider(ProviderConfig(provider="vllm", model="served-model", api_key="unused"))

    built = _build_provider(
        ProviderConfig(
            provider="vllm",
            model="served-model",
            api_key="unused",
            base_url="http://localhost:8001/v1",
        )
    )

    assert isinstance(built, OpenAIProvider)


def test_azure_default_construction_is_outside_a_stage_support() -> None:
    with pytest.raises(ProviderBuildError, match="requires an explicit base_url"):
        _build_provider(
            ProviderConfig(provider="azure", model="deployment-name", api_key="test-key")
        )
