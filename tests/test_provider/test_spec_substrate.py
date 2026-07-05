"""Consistency tests for the ProviderSpec substrate fields.

Covers the spec-carried ``catalog_source`` mapping (migrated from the
models.dev snapshot refresh script) and the ``auth_header_style`` values the
anthropic backend consumes.
"""

from __future__ import annotations

from opensquilla.provider.registry import get_provider_spec, list_provider_specs

# Runtime-supported providers legitimately absent from the models.dev
# catalog mapping. Every id must carry a reason; anything else that is
# runtime-supported needs a non-empty catalog_source.
_CATALOG_SOURCE_WAIVERS: frozenset[str] = frozenset(
    {
        # Local/self-hosted runtimes: the model list comes from the local
        # server itself, not a public catalog.
        "ollama",
        "lm_studio",
        "ovms",
        "vllm",
        # Deployment-defined aggregation proxy: the model set is whatever
        # the operator's LiteLLM instance routes; no stable public catalog.
        "litellm_proxy",
        # Hosted aggregator with no models.dev source mapped; the vendored
        # snapshot has never carried aihubmix rows.
        "aihubmix",
        # OAuth-only ChatGPT-backend provider: models are fixed by the
        # Codex subscription, not a public catalog.
        "openai_codex",
    }
)

# Frozen copy of the mapping that previously lived out-of-band as
# PROVIDER_SOURCES in scripts/refresh_models_dev_snapshot.py. The script now
# derives its mapping from the registry; this literal proves the migration
# moved the data verbatim.
_EXPECTED_CATALOG_SOURCES: dict[str, tuple[str, ...]] = {
    "openrouter": ("openrouter",),
    "openai": ("openai",),
    "openai_responses": ("openai",),
    "anthropic": ("anthropic",),
    "deepseek": ("deepseek",),
    "gemini": ("google",),
    "dashscope": ("alibaba-cn", "alibaba"),
    "bailian_coding": ("alibaba", "alibaba-cn"),
    "moonshot": ("moonshotai",),
    "zhipu": ("zhipuai", "zai"),
    "minimax": ("minimax",),
    "minimax_openai": ("minimax",),
    "minimax_cn": ("minimax",),
    "minimax_global": ("minimax",),
    "mistral": ("mistral",),
    "groq": ("groq",),
    "siliconflow": ("siliconflow",),
    "volcengine": ("volcengine",),
    "byteplus": ("byteplus",),
    "qianfan": ("qianfan", "baidu"),
    "azure": ("azure",),
}


def test_every_runtime_supported_spec_has_catalog_source_or_waiver() -> None:
    for spec in list_provider_specs():
        if not spec.runtime_supported:
            continue
        assert spec.catalog_source or spec.provider_id in _CATALOG_SOURCE_WAIVERS, (
            f"Provider '{spec.provider_id}' is runtime-supported but declares no "
            "catalog_source. Map it to its models.dev source ids, or add it to "
            "_CATALOG_SOURCE_WAIVERS with a reason."
        )


def test_waivers_only_cover_specs_without_catalog_sources() -> None:
    for provider_id in sorted(_CATALOG_SOURCE_WAIVERS):
        spec = get_provider_spec(provider_id)  # also fails on stale waiver ids
        assert not spec.catalog_source, (
            f"Provider '{provider_id}' declares a catalog_source; drop it from "
            "_CATALOG_SOURCE_WAIVERS."
        )


def test_catalog_sources_match_the_migrated_script_mapping() -> None:
    actual = {
        spec.provider_id: spec.catalog_source
        for spec in list_provider_specs()
        if spec.catalog_source
    }
    assert actual == _EXPECTED_CATALOG_SOURCES


def test_anthropic_backend_auth_header_styles() -> None:
    """Anthropic proper signs with x-api-key; the MiniMax Anthropic-compatible
    endpoints require Authorization: Bearer. The request goldens freeze the
    wire effect; this pins the spec values that drive it."""
    assert get_provider_spec("anthropic").auth_header_style == "x-api-key"
    for provider_id in ("minimax", "minimax_cn", "minimax_global"):
        spec = get_provider_spec(provider_id)
        assert spec.backend == "anthropic"
        assert spec.auth_header_style == "bearer"
