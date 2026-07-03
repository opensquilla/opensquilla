from __future__ import annotations

from opensquilla.provider.selector import ModelSelector, ProviderConfig, SelectorConfig

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
