"""Config contract for squilla_router.tier_provider_mismatch.

Additive Literal["route","veto"] key. The default must be "route" (the
historical flag-and-misroute behavior), and the section's extra="ignore"
must keep both directions of an rc1 up/downgrade loadable: rc1 payloads
without the key load with the default, and rc1 loaders reading a payload
that carries the key simply drop it.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from opensquilla.gateway.config import GatewayConfig, SquillaRouterConfig


def test_default_is_route() -> None:
    assert SquillaRouterConfig().tier_provider_mismatch == "route"
    assert GatewayConfig().squilla_router.tier_provider_mismatch == "route"


def test_veto_value_accepted() -> None:
    assert SquillaRouterConfig(tier_provider_mismatch="veto").tier_provider_mismatch == "veto"
    config = GatewayConfig(squilla_router={"tier_provider_mismatch": "veto"})
    assert config.squilla_router.tier_provider_mismatch == "veto"


def test_invalid_value_rejected() -> None:
    with pytest.raises(ValidationError):
        SquillaRouterConfig(tier_provider_mismatch="abort")


def test_rc1_shape_payload_without_key_loads_default() -> None:
    # An rc1-era section knows nothing about the key: defaults apply.
    rc1_payload = {
        "enabled": True,
        "rollout_phase": "full",
        "default_tier": "c1",
    }
    config = SquillaRouterConfig(**rc1_payload)
    assert config.tier_provider_mismatch == "route"


def test_extra_ignore_tolerates_unknown_router_keys() -> None:
    # The section is extra="ignore" — the same tolerance that lets an rc1
    # loader drop tier_provider_mismatch lets current loaders drop future
    # unknown keys alongside it.
    config = SquillaRouterConfig(
        tier_provider_mismatch="veto",
        some_future_router_knob="whatever",  # type: ignore[call-arg]
    )
    assert config.tier_provider_mismatch == "veto"
    assert not hasattr(config, "some_future_router_knob")


def test_key_round_trips_through_toml_dict() -> None:
    config = GatewayConfig(squilla_router={"tier_provider_mismatch": "veto"})
    data = config.to_toml_dict()
    assert data["squilla_router"]["tier_provider_mismatch"] == "veto"
    # And the dump reloads cleanly on the current schema.
    reloaded = GatewayConfig(squilla_router=data["squilla_router"])
    assert reloaded.squilla_router.tier_provider_mismatch == "veto"
