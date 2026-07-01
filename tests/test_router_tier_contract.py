"""Typed router-tier contract: TierConfig, misroute detection, override helper."""

from __future__ import annotations

from types import SimpleNamespace

from opensquilla.engine.selector_override import apply_model_override
from opensquilla.engine.steps.squilla_router import _flag_tier_provider_mismatch
from opensquilla.gateway.config import GatewayConfig
from opensquilla.onboarding.mutations import _cross_provider_tier_warnings, upsert_router
from opensquilla.router_tiers import TierConfig

# ---------------------------------------------------------------------------
# TierConfig
# ---------------------------------------------------------------------------


def test_tier_config_from_dict() -> None:
    tier = TierConfig.from_value(
        {
            "provider": " openrouter ",
            "model": "deepseek/deepseek-v4-flash",
            "thinking_level": "low",
            "supports_image": True,
        }
    )
    assert tier.provider == "openrouter"
    assert tier.model == "deepseek/deepseek-v4-flash"
    assert tier.thinking_level == "low"
    assert tier.supports_image is True
    assert tier.image_only is False


def test_tier_config_from_object_and_none() -> None:
    obj = SimpleNamespace(provider="openai", model="gpt-5.4-nano", image_only=True)
    tier = TierConfig.from_value(obj)
    assert tier.provider == "openai"
    assert tier.image_only is True
    assert TierConfig.from_value(None) == TierConfig()
    assert TierConfig.from_value({}) == TierConfig()


# ---------------------------------------------------------------------------
# Tier provider mismatch detection
# ---------------------------------------------------------------------------


def _ctx(active_provider: str) -> SimpleNamespace:
    return SimpleNamespace(
        metadata={},
        config=SimpleNamespace(llm=SimpleNamespace(provider=active_provider)),
        session_key="s1",
    )


def test_mismatched_tier_provider_is_flagged() -> None:
    ctx = _ctx("openrouter")
    tiers = {"c2": {"provider": "openai", "model": "gpt-5.5"}}
    _flag_tier_provider_mismatch(ctx, tiers, "c2", routing_applied=True)
    assert ctx.metadata["router_tier_provider_mismatch"] == "openai"


def test_matching_tier_provider_is_not_flagged() -> None:
    ctx = _ctx("openrouter")
    tiers = {"c2": {"provider": "openrouter", "model": "z-ai/glm-5.1"}}
    _flag_tier_provider_mismatch(ctx, tiers, "c2", routing_applied=True)
    assert "router_tier_provider_mismatch" not in ctx.metadata


def test_observe_phase_does_not_flag() -> None:
    ctx = _ctx("openrouter")
    tiers = {"c2": {"provider": "openai", "model": "gpt-5.5"}}
    _flag_tier_provider_mismatch(ctx, tiers, "c2", routing_applied=False)
    assert "router_tier_provider_mismatch" not in ctx.metadata


# ---------------------------------------------------------------------------
# Shared selector-override helper
# ---------------------------------------------------------------------------


class _StubSelector:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def override_model(self, model: str) -> None:
        self.calls.append(("override_model", model))

    def override_model_with_fallback_chain(self, model: str, chain: list) -> None:
        self.calls.append(("override_with_chain", (model, chain)))

    def resolve(self) -> object:
        return "provider-sentinel"


def test_override_uses_fallback_chain_when_routing_applied() -> None:
    selector = _StubSelector()
    metadata = {
        "routing_applied": True,
        "router_fallback_chain": [{"tier": "c0", "model": "cheap"}],
        "routed_model": "routed",
    }
    provider = apply_model_override(
        selector, "routed", turn_metadata=metadata, realign_routed_model=False
    )
    assert provider == "provider-sentinel"
    assert selector.calls[0][0] == "override_with_chain"
    assert metadata["routed_model"] == "routed"


def test_override_without_routing_uses_plain_override() -> None:
    selector = _StubSelector()
    metadata = {"routing_applied": False, "routed_model": "would-be-routed"}
    apply_model_override(
        selector, "baseline", turn_metadata=metadata, realign_routed_model=False
    )
    assert selector.calls[0][0] == "override_model"
    # Observe phase: routed_model intentionally keeps the would-be choice.
    assert metadata["routed_model"] == "would-be-routed"


def test_explicit_override_realigns_routed_model_and_drops_savings() -> None:
    selector = _StubSelector()
    metadata = {
        "routing_applied": True,
        "router_fallback_chain": [],
        "routed_model": "routed",
        "savings_pct": 10.0,
        "savings_max_price_per_m": 3.0,
    }
    apply_model_override(
        selector, "explicit", turn_metadata=metadata, realign_routed_model=True
    )
    assert metadata["routed_model"] == "explicit"
    assert metadata["savings_pct"] == 0.0
    assert metadata["savings_max_price_per_m"] == 0.0


# ---------------------------------------------------------------------------
# Onboarding warnings for cross-provider tiers
# ---------------------------------------------------------------------------


def test_cross_provider_tier_warning_text() -> None:
    warnings = _cross_provider_tier_warnings(
        {"c2": {"provider": "openai", "model": "gpt-5.5"}},
        "openrouter",
    )
    assert len(warnings) == 1
    assert "'c2'" in warnings[0]
    assert "'openai'" in warnings[0]
    assert "not supported yet" in warnings[0]


def test_upsert_router_surfaces_cross_provider_warning() -> None:
    cfg = GatewayConfig()  # defaults: openrouter provider + openrouter tiers
    res = upsert_router(
        cfg,
        mode="recommended",
        tiers={"c2": {"provider": "openai", "model": "gpt-5.5"}},
    )
    assert any("cross-provider" in w.lower() for w in res.warnings)


def test_upsert_router_no_warning_for_matching_tiers() -> None:
    cfg = GatewayConfig()
    res = upsert_router(cfg, mode="recommended")
    assert res.warnings == []
