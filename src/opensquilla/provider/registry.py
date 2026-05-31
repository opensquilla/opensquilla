"""Metadata registry for LLM and coding provider capabilities."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar, Literal

ProviderBackend = Literal[
    "openai_compat",
    "openai_responses",
    "anthropic",
    "ollama",
    "unsupported_oauth",
    "unsupported_responses",
]
ProviderSupportLevel = Literal[
    "native",
    "compat_mock_verified",
    "compat_configured",
    "metadata_only",
    "unsupported_for_A",
    "live_verified",
]


@dataclass(frozen=True)
class ProviderSpec:
    """Static provider metadata used for selection and capability display."""

    provider_id: str
    backend: ProviderBackend
    provider_kind: str
    env_key: str = ""
    default_base_url: str = ""
    support_level: ProviderSupportLevel = "compat_mock_verified"
    required_fields: frozenset[str] = field(default_factory=lambda: frozenset({"api_key", "model"}))
    reasoning_shape: str = "none"
    usage_shape: str = "openai_compat"
    failure_family: str = "openai_compat"
    metadata_supported: bool = True
    runtime_supported: bool = True
    capabilities: frozenset[str] = field(default_factory=lambda: frozenset({"chat"}))

    _LOCAL_PROVIDERS: ClassVar[frozenset[str]] = frozenset(
        {"ollama", "lm_studio", "ovms"}
    )

    def requires_api_key(self) -> bool:
        """True if onboarding must collect an API key for this provider."""
        if self.provider_id in self._LOCAL_PROVIDERS:
            return False
        return bool(self.env_key) and self.env_key != "OAuth"

    def requires_base_url(self) -> bool:
        """True if onboarding must collect a base URL for this provider."""
        return self.runtime_supported and not self.default_base_url


class UnknownProviderError(ValueError):
    """Raised when a provider id is not present in the registry."""


_PROVIDER_SPECS: dict[str, ProviderSpec] = {}


def _register(spec: ProviderSpec) -> None:
    _PROVIDER_SPECS[spec.provider_id] = spec


def _spec(
    provider_id: str,
    backend: ProviderBackend,
    provider_kind: str,
    env_key: str = "",
    default_base_url: str = "",
    *,
    support_level: ProviderSupportLevel = "compat_mock_verified",
    required_fields: frozenset[str] | None = None,
    reasoning_shape: str = "none",
    usage_shape: str = "openai_compat",
    failure_family: str = "openai_compat",
    runtime_supported: bool = True,
    capabilities: frozenset[str] | None = None,
) -> ProviderSpec:
    if required_fields is None:
        required_fields = frozenset({"api_key", "model"}) if env_key else frozenset({"model"})
    return ProviderSpec(
        provider_id=provider_id,
        backend=backend,
        provider_kind=provider_kind,
        env_key=env_key,
        default_base_url=default_base_url,
        support_level=support_level,
        required_fields=required_fields,
        reasoning_shape=reasoning_shape,
        usage_shape=usage_shape,
        failure_family=failure_family,
        runtime_supported=runtime_supported,
        capabilities=capabilities or frozenset({"chat"}),
    )


for _provider_spec in [
    _spec(
        "openrouter",
        "openai_compat",
        "openrouter",
        "OPENROUTER_API_KEY",
        "https://openrouter.ai/api/v1",
    ),
    _spec("openai", "openai_compat", "openai", "OPENAI_API_KEY", "https://api.openai.com/v1"),
    _spec(
        "openai_responses",
        "openai_responses",
        "openai_responses",
        "OPENAI_API_KEY",
        "https://api.openai.com/v1",
        support_level="native",
        usage_shape="openai_responses",
        capabilities=frozenset({"chat", "responses"}),
    ),
    _spec(
        "azure",
        "openai_compat",
        "azure",
        "AZURE_OPENAI_API_KEY",
        support_level="unsupported_for_A",
    ),
    _spec(
        "anthropic",
        "anthropic",
        "anthropic",
        "ANTHROPIC_API_KEY",
        "https://api.anthropic.com",
        support_level="native",
        usage_shape="anthropic",
        failure_family="anthropic",
    ),
    _spec(
        "ollama",
        "ollama",
        "ollama",
        default_base_url="http://localhost:11434",
        support_level="native",
        failure_family="ollama",
    ),
    _spec(
        "deepseek",
        "openai_compat",
        "deepseek",
        "DEEPSEEK_API_KEY",
        "https://api.deepseek.com",
        reasoning_shape="deepseek",
        usage_shape="deepseek",
    ),
    _spec(
        "gemini",
        "openai_compat",
        "gemini",
        "GEMINI_API_KEY",
        "https://generativelanguage.googleapis.com/v1beta/openai",
        reasoning_shape="gemini",
    ),
    _spec(
        "dashscope",
        "openai_compat",
        "dashscope",
        "DASHSCOPE_API_KEY",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
    ),
    _spec(
        "bailian_coding",
        "openai_compat",
        "bailian_coding",
        "BAILIAN_API_KEY",
        "https://coding-intl.dashscope.aliyuncs.com/v1",
        support_level="compat_configured",
    ),
    _spec(
        "moonshot",
        "openai_compat",
        "moonshot",
        "MOONSHOT_API_KEY",
        "https://api.moonshot.ai/v1",
    ),
    _spec(
        "minimax",
        "anthropic",
        "minimax",
        "MINIMAX_API_KEY",
        "https://api.minimaxi.com/anthropic",
        support_level="compat_configured",
        usage_shape="anthropic",
        failure_family="anthropic",
    ),
    _spec(
        "minimax_openai",
        "openai_compat",
        "minimax",
        "MINIMAX_API_KEY",
        "https://api.minimaxi.com/v1",
        support_level="compat_configured",
    ),
    _spec(
        "minimax_cn",
        "anthropic",
        "minimax",
        "MINIMAX_CN_API_KEY",
        "https://api.minimaxi.com/anthropic",
        support_level="compat_configured",
        usage_shape="anthropic",
        failure_family="anthropic",
    ),
    _spec(
        "minimax_global",
        "anthropic",
        "minimax",
        "MINIMAX_API_KEY",
        "https://api.minimax.io/anthropic",
        support_level="compat_configured",
        usage_shape="anthropic",
        failure_family="anthropic",
    ),
    _spec("mistral", "openai_compat", "mistral", "MISTRAL_API_KEY", "https://api.mistral.ai/v1"),
    _spec("groq", "openai_compat", "groq", "GROQ_API_KEY", "https://api.groq.com/openai/v1"),
    _spec(
        "zhipu",
        "openai_compat",
        "zhipu",
        "ZAI_API_KEY",
        "https://open.bigmodel.cn/api/paas/v4",
        reasoning_shape="zai",
    ),
    _spec(
        "qianfan",
        "openai_compat",
        "qianfan",
        "QIANFAN_API_KEY",
        "https://qianfan.baidubce.com/v2",
        support_level="compat_configured",
    ),
    _spec(
        "siliconflow",
        "openai_compat",
        "siliconflow",
        "SILICONFLOW_API_KEY",
        "https://api.siliconflow.cn/v1",
    ),
    _spec(
        "aihubmix",
        "openai_compat",
        "aihubmix",
        "AIHUBMIX_API_KEY",
        "https://aihubmix.com/v1",
        support_level="compat_configured",
    ),
    _spec(
        "volcengine",
        "openai_compat",
        "volcengine",
        "VOLCENGINE_API_KEY",
        "https://ark.cn-beijing.volces.com/api/v3",
    ),
    _spec(
        "byteplus",
        "openai_compat",
        "byteplus",
        "BYTEPLUS_API_KEY",
        "https://ark.ap-southeast.bytepluses.com/api/v3",
    ),
    _spec("vllm", "openai_compat", "openai"),
    _spec("lm_studio", "openai_compat", "lm_studio", default_base_url="http://localhost:1234/v1"),
    _spec("ovms", "openai_compat", "ovms", default_base_url="http://localhost:8000/v3"),
    _spec(
        "volcengine_coding_plan",
        "openai_compat",
        "openai",
        "VOLCENGINE_API_KEY",
        "https://ark.cn-beijing.volces.com/api/coding/v3",
        runtime_supported=False,
        capabilities=frozenset({"coding_plan"}),
    ),
    _spec(
        "byteplus_coding_plan",
        "openai_compat",
        "openai",
        "BYTEPLUS_API_KEY",
        "https://ark.ap-southeast.bytepluses.com/api/coding/v3",
        runtime_supported=False,
        capabilities=frozenset({"coding_plan"}),
    ),
    _spec(
        "openai_codex",
        "unsupported_oauth",
        "openai_codex",
        "OAuth",
        "https://chatgpt.com/backend-api",
        runtime_supported=False,
        capabilities=frozenset({"coding_plan"}),
    ),
    _spec(
        "github_copilot",
        "unsupported_oauth",
        "github_copilot",
        "OAuth",
        "https://api.githubcopilot.com",
        runtime_supported=False,
        capabilities=frozenset({"coding_plan"}),
    ),
]:
    _register(_provider_spec)


def list_provider_specs() -> tuple[ProviderSpec, ...]:
    """Return provider specs sorted by provider id for stable display/tests."""

    return tuple(_PROVIDER_SPECS[name] for name in sorted(_PROVIDER_SPECS))


def list_provider_names() -> tuple[str, ...]:
    """Return registered provider ids in stable order."""

    return tuple(spec.provider_id for spec in list_provider_specs())


def get_provider_spec(provider_id: str) -> ProviderSpec:
    """Return a provider spec or raise an actionable unknown-provider error."""

    try:
        return _PROVIDER_SPECS[provider_id]
    except KeyError as exc:
        available = ", ".join(list_provider_names())
        raise UnknownProviderError(
            f"Unknown provider '{provider_id}'. Available: {available}"
        ) from exc
