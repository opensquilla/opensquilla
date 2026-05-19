from opensquilla.gateway.config import (
    ROUTER_TIER_PROFILE_IDS,
    _default_tiers,
    _merge_tier_dicts,
    _router_tier_profile_defaults,
)
from opensquilla.provider.model_catalog import openrouter_pricing_model_ids
from opensquilla.provider.router_profiles import (
    ROUTER_TIER_PROFILE_IDS as PROVIDER_ROUTER_TIER_PROFILE_IDS,
)
from opensquilla.provider.router_profiles import (
    default_router_tiers,
    merge_router_tier_dicts,
    router_tier_profile_defaults,
)


def test_gateway_router_profile_compatibility_wrappers_delegate_to_provider_boundary() -> None:
    assert ROUTER_TIER_PROFILE_IDS == PROVIDER_ROUTER_TIER_PROFILE_IDS
    assert _default_tiers() == default_router_tiers()
    assert _router_tier_profile_defaults("openai") == router_tier_profile_defaults("openai")
    assert _merge_tier_dicts({"t1": {"model": "base"}}, {"t1": {"thinking_level": "high"}}) == (
        merge_router_tier_dicts(
            {"t1": {"model": "base"}},
            {"t1": {"thinking_level": "high"}},
        )
    )


def test_provider_router_profile_defaults_are_fresh_mutable_copies() -> None:
    first = router_tier_profile_defaults("moonshot")
    second = router_tier_profile_defaults("moonshot")

    first["t0"]["model"] = "mutated"

    assert second["t0"]["model"] == "kimi-k2.5"
    assert second["t3"]["provider"] == "moonshot"
    assert "image_model" not in second


def test_openrouter_pricing_model_ids_accepts_provider_router_profile_defaults() -> None:
    tiers = router_tier_profile_defaults("openrouter")

    pricing_ids = openrouter_pricing_model_ids("deepseek/deepseek-v4-flash", tiers)

    assert "deepseek/deepseek-v4-flash" in pricing_ids
    assert "z-ai/glm-5.1" in pricing_ids
    assert "anthropic/claude-opus-4.7" in pricing_ids
    assert "moonshotai/kimi-k2.6" in pricing_ids
