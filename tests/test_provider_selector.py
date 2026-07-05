from __future__ import annotations

from opensquilla.provider.failures import ProviderFailureKind
from opensquilla.provider.selector import ModelSelector, ProviderConfig, SelectorConfig
from opensquilla.provider.types import ModelInfo

HIGH_TIER_MODEL = "openrouter/high-tier-region-locked"
MID_TIER_MODEL = "openrouter/mid-tier-available"
LOW_TIER_MODEL = "openrouter/low-tier-available"
BASELINE_MODEL = "openrouter/baseline-available"


def test_clone_isolates_config_from_original_mutation() -> None:
    primary = ProviderConfig(
        provider="anthropic", model="a", api_key="ka", provider_routing={"a": "x"}
    )
    fallback = ProviderConfig(provider="ollama", model="b")
    selector = ModelSelector(SelectorConfig(primary=primary, fallbacks=[fallback]))

    clone = selector.clone()

    # The clone owns its own config objects, not the originals.
    assert clone.current_config is not primary
    assert clone.current_config.provider_routing is not primary.provider_routing

    # Rebinding the original primary and editing the original routing dict
    # in place must not leak into the already-cloned selector.
    selector.sync_primary(ProviderConfig(provider="openai", model="c"))
    primary.provider_routing["a"] = "MUTATED"

    assert clone.current_config.provider == "anthropic"
    assert clone.current_config.model == "a"
    assert clone.current_config.provider_routing == {"a": "x"}


def test_override_model_keeps_original_primary_as_first_fallback(monkeypatch) -> None:
    built: list[ProviderConfig] = []

    def fake_build_provider(cfg: ProviderConfig) -> ProviderConfig:
        built.append(cfg)
        return cfg

    monkeypatch.setattr("opensquilla.provider.selector._build_provider", fake_build_provider)
    selector = ModelSelector(
        SelectorConfig(
            primary=ProviderConfig(
                provider="openrouter",
                model=BASELINE_MODEL,
                api_key="sk-test",
                base_url="https://openrouter.ai/api",
            )
        )
    )

    selector.override_model(HIGH_TIER_MODEL)
    primary = selector.resolve()
    fallback = selector.next_fallback_after_failure(
        RuntimeError("HTTP 403: This model is not available in your region.")
    )

    assert primary.model == HIGH_TIER_MODEL
    assert fallback.model == BASELINE_MODEL
    assert fallback.provider == "openrouter"
    assert [cfg.model for cfg in built] == [
        HIGH_TIER_MODEL,
        BASELINE_MODEL,
    ]


def test_override_model_with_router_fallback_chain_prefers_lower_tiers(monkeypatch) -> None:
    built: list[ProviderConfig] = []

    def fake_build_provider(cfg: ProviderConfig) -> ProviderConfig:
        built.append(cfg)
        return cfg

    monkeypatch.setattr("opensquilla.provider.selector._build_provider", fake_build_provider)
    selector = ModelSelector(
        SelectorConfig(
            primary=ProviderConfig(
                provider="openrouter",
                model=BASELINE_MODEL,
                api_key="sk-test",
                base_url="https://openrouter.ai/api",
            )
        )
    )

    selector.override_model_with_fallback_chain(
        HIGH_TIER_MODEL,
        [
            {"tier": "c2", "provider": "openrouter", "model": MID_TIER_MODEL},
            {"tier": "c1", "provider": "openrouter", "model": BASELINE_MODEL},
            {"tier": "c0", "provider": "openrouter", "model": LOW_TIER_MODEL},
        ],
    )

    resolved_models = [selector.resolve().model]
    for _ in range(3):
        resolved_models.append(
            selector.next_fallback_after_failure(
                RuntimeError("HTTP 403: This model is not available in your region.")
            ).model
        )

    assert resolved_models == [
        HIGH_TIER_MODEL,
        MID_TIER_MODEL,
        BASELINE_MODEL,
        LOW_TIER_MODEL,
    ]
    assert [cfg.model for cfg in built] == resolved_models


# A synthetic, public-dummy credential: it only exists to prove redaction.
FAKE_LEAKED_KEY = "sk-test-000fakefakefakefake"


class _AuthRejectingProvider:
    async def list_models(self) -> list[ModelInfo]:
        raise RuntimeError(f"HTTP 401: invalid api key {FAKE_LEAKED_KEY}")


class _HealthyProvider:
    async def list_models(self) -> list[ModelInfo]:
        return [ModelInfo(provider="ollama", model_id="test-model-good")]


def _selector_with_failing_primary(monkeypatch) -> ModelSelector:
    def fake_build_provider(cfg: ProviderConfig):
        if cfg.provider == "openrouter":
            return _AuthRejectingProvider()
        return _HealthyProvider()

    monkeypatch.setattr("opensquilla.provider.selector._build_provider", fake_build_provider)
    return ModelSelector(
        SelectorConfig(
            primary=ProviderConfig(
                provider="openrouter",
                model="openrouter/auth-locked",
                api_key=FAKE_LEAKED_KEY,
            ),
            fallbacks=[ProviderConfig(provider="ollama", model="test-model-good")],
        )
    )


async def test_list_models_detailed_classifies_and_redacts_auth_failures(monkeypatch) -> None:
    selector = _selector_with_failing_primary(monkeypatch)

    result = await selector.list_models_detailed()

    # The healthy provider's models still come through.
    assert [m["model_id"] for m in result.models] == ["test-model-good"]

    assert len(result.errors) == 1
    error = result.errors[0]
    assert error.provider == "openrouter"
    assert error.model_hint == "openrouter/auth-locked"
    assert error.kind == ProviderFailureKind.AUTH_INVALID.value
    # The provider echoed the bad key back; the surfaced detail must not.
    assert FAKE_LEAKED_KEY not in error.detail
    assert "***" in error.detail
    assert "invalid api key" in error.detail


async def test_list_models_delegates_to_detailed_and_drops_errors(monkeypatch) -> None:
    selector = _selector_with_failing_primary(monkeypatch)

    models = await selector.list_models()

    # Public behavior unchanged: failed links are skipped, good models kept.
    assert models == (await selector.list_models_detailed()).models
    assert [m["model_id"] for m in models] == ["test-model-good"]


async def test_list_models_detailed_reports_every_failed_chain_link(monkeypatch) -> None:
    def fake_build_provider(cfg: ProviderConfig):
        return _AuthRejectingProvider()

    monkeypatch.setattr("opensquilla.provider.selector._build_provider", fake_build_provider)
    selector = ModelSelector(
        SelectorConfig(
            primary=ProviderConfig(provider="openrouter", model="openrouter/auth-locked-a"),
            fallbacks=[ProviderConfig(provider="deepseek", model="deepseek/auth-locked-b")],
        )
    )

    result = await selector.list_models_detailed()

    assert result.models == []
    assert [(e.provider, e.model_hint) for e in result.errors] == [
        ("openrouter", "openrouter/auth-locked-a"),
        ("deepseek", "deepseek/auth-locked-b"),
    ]
