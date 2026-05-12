"""Onboarding-friendly provider catalog derived from provider.registry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from opensquilla.gateway.config import ROUTER_TIER_PROFILE_IDS, _router_tier_profile_defaults
from opensquilla.provider.registry import ProviderSpec, list_provider_specs

FieldType = Literal["text", "password", "select", "bool"]


@dataclass(frozen=True)
class ProviderSetupField:
    name: str
    label: str
    field_type: FieldType
    required: bool
    default: str | bool | None = None
    description: str = ""
    secret: bool = False


@dataclass(frozen=True)
class ProviderSetupSpec:
    provider_id: str
    label: str
    backend: str
    provider_kind: str
    runtime_supported: bool
    env_key: str
    default_base_url: str
    requires_api_key: bool
    requires_base_url: bool
    router_supported: bool
    default_direct_model: str
    capabilities: tuple[str, ...]
    fields: tuple[ProviderSetupField, ...]


_PROVIDER_LABELS: dict[str, str] = {
    "openrouter": "OpenRouter",
    "openai": "OpenAI",
    "azure": "Azure OpenAI",
    "anthropic": "Anthropic",
    "ollama": "Ollama (local)",
    "deepseek": "DeepSeek",
    "gemini": "Google Gemini",
    "dashscope": "Aliyun DashScope",
    "bailian_coding": "Bailian Coding",
    "moonshot": "Moonshot AI",
    "minimax": "MiniMax",
    "minimax_openai": "MiniMax OpenAI-compatible",
    "minimax_cn": "MiniMax Mainland",
    "minimax_global": "MiniMax Global",
    "mistral": "Mistral",
    "groq": "Groq",
    "zhipu": "Zhipu (Z.AI)",
    "qianfan": "Baidu Qianfan",
    "siliconflow": "SiliconFlow",
    "aihubmix": "AIHubMix",
    "volcengine": "Volcengine Ark",
    "byteplus": "BytePlus Ark",
    "vllm": "vLLM (self-hosted)",
    "lm_studio": "LM Studio (local)",
    "ovms": "OpenVINO Model Server",
    "volcengine_coding_plan": "Volcengine Coding Plan",
    "byteplus_coding_plan": "BytePlus Coding Plan",
    "openai_codex": "OpenAI Codex (OAuth)",
    "github_copilot": "GitHub Copilot (OAuth)",
}

_ONBOARDING_VERIFIED_PROVIDER_IDS = frozenset(
    {
        "openrouter",
        "openai",
        "anthropic",
        "ollama",
        "deepseek",
        "gemini",
        "dashscope",
        "moonshot",
        "zhipu",
        "qianfan",
        "volcengine",
    }
)


def _default_direct_model(provider_id: str) -> str:
    if provider_id in ROUTER_TIER_PROFILE_IDS:
        tiers = _router_tier_profile_defaults(provider_id)
        tier = tiers.get("t1") or tiers.get("t0") or {}
        return str(tier.get("model") or "")
    return ""


def _fields_for(spec: ProviderSpec) -> tuple[ProviderSetupField, ...]:
    router_supported = spec.provider_id in ROUTER_TIER_PROFILE_IDS
    return (
        ProviderSetupField(
            name="model",
            label="Model id",
            field_type="text",
            required=not router_supported,
            default=_default_direct_model(spec.provider_id),
            description=(
                "Direct fallback model. Router-supported providers can leave this "
                "blank to use the selected router default tier."
            ),
        ),
        ProviderSetupField(
            name="api_key",
            label="API key",
            field_type="password",
            required=spec.requires_api_key(),
            default="",
            description=(
                f"Stored under env key {spec.env_key}." if spec.env_key else ""
            ),
            secret=True,
        ),
        ProviderSetupField(
            name="base_url",
            label="Base URL",
            field_type="text",
            required=spec.requires_base_url(),
            default=spec.default_base_url,
            description="Override the upstream HTTP base URL.",
        ),
        ProviderSetupField(
            name="proxy",
            label="HTTP proxy",
            field_type="text",
            required=False,
            default="",
            description=(
                "Optional explicit HTTP proxy URL "
                "(e.g. http://127.0.0.1:7890)."
            ),
        ),
    )


def _to_setup_spec(spec: ProviderSpec) -> ProviderSetupSpec:
    runtime_supported = (
        spec.runtime_supported
        and spec.provider_id in _ONBOARDING_VERIFIED_PROVIDER_IDS
    )
    return ProviderSetupSpec(
        provider_id=spec.provider_id,
        label=_PROVIDER_LABELS.get(spec.provider_id, spec.provider_id),
        backend=spec.backend,
        provider_kind=spec.provider_kind,
        runtime_supported=runtime_supported,
        env_key=spec.env_key,
        default_base_url=spec.default_base_url,
        requires_api_key=spec.requires_api_key(),
        requires_base_url=spec.requires_base_url(),
        router_supported=spec.provider_id in ROUTER_TIER_PROFILE_IDS,
        default_direct_model=_default_direct_model(spec.provider_id),
        capabilities=tuple(sorted(spec.capabilities)),
        fields=_fields_for(spec),
    )


def list_provider_setup_specs() -> list[ProviderSetupSpec]:
    specs = [_to_setup_spec(s) for s in list_provider_specs()]
    return sorted(
        specs,
        key=lambda s: (
            0 if s.provider_id == "openrouter" else 1,
            s.label.lower(),
            s.provider_id,
        ),
    )


def get_provider_setup_spec(provider_id: str) -> ProviderSetupSpec:
    for spec in list_provider_setup_specs():
        if spec.provider_id == provider_id:
            return spec
    raise KeyError(f"unknown provider: {provider_id!r}")


def provider_catalog_payload() -> list[dict[str, Any]]:
    return [
        {
            "providerId": s.provider_id,
            "label": s.label,
            "backend": s.backend,
            "providerKind": s.provider_kind,
            "runtimeSupported": s.runtime_supported,
            "envKey": s.env_key,
            "defaultBaseUrl": s.default_base_url,
            "requiresApiKey": s.requires_api_key,
            "requiresBaseUrl": s.requires_base_url,
            "routerSupported": s.router_supported,
            "defaultDirectModel": s.default_direct_model,
            "capabilities": list(s.capabilities),
            "fields": [
                {
                    "name": f.name,
                    "label": f.label,
                    "type": f.field_type,
                    "required": f.required,
                    "default": f.default,
                    "description": f.description,
                    "secret": f.secret,
                }
                for f in s.fields
            ],
        }
        for s in list_provider_setup_specs()
        if s.runtime_supported
    ]
