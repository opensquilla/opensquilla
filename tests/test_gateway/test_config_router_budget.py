"""Config contract for squilla_router.budget (the router budget gate).

Additive, nested, opt-in block. The default must be a complete no-op (no
``limit_usd`` ceiling, ``action="warn"``), nothing that activates the gate is
persisted while unset, and the block must round-trip losslessly. The section's
``extra="ignore"`` keeps it downgrade-tolerant: an older loader reading a
payload that carries budget keys simply drops the unknown ones.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from opensquilla.gateway.config import (
    GatewayConfig,
    RouterBudgetConfig,
    SquillaRouterConfig,
)


def test_default_is_noop() -> None:
    budget = SquillaRouterConfig().budget
    assert budget.action == "warn"
    assert budget.limit_usd is None
    assert budget.cap_tier is None
    assert budget.include_next_turn_estimate is False
    # Same through the composed gateway config.
    assert GatewayConfig().squilla_router.budget.limit_usd is None


def test_active_values_accepted() -> None:
    config = GatewayConfig(
        squilla_router={
            "budget": {"action": "cap", "limit_usd": 2.5, "cap_tier": "c0"}
        }
    )
    budget = config.squilla_router.budget
    assert budget.action == "cap"
    assert budget.limit_usd == 2.5
    assert budget.cap_tier == "c0"


def test_invalid_action_rejected() -> None:
    with pytest.raises(ValidationError):
        RouterBudgetConfig(action="downgrade")  # type: ignore[arg-type]


def test_nothing_activating_persists_when_unset() -> None:
    # exclude_none drops the None ceiling/cap_tier, so an unset budget persists
    # nothing that could activate the gate.
    dumped = GatewayConfig().to_toml_dict()["squilla_router"]["budget"]
    assert "limit_usd" not in dumped
    assert "cap_tier" not in dumped
    # The default no-op action is all that remains.
    assert dumped == {"action": "warn", "include_next_turn_estimate": False}


def test_block_round_trips_through_toml_dict() -> None:
    config = GatewayConfig(
        squilla_router={
            "budget": {
                "action": "cap",
                "limit_usd": 4.0,
                "cap_tier": "c1",
                "include_next_turn_estimate": True,
            }
        }
    )
    data = config.to_toml_dict()
    assert data["squilla_router"]["budget"] == {
        "action": "cap",
        "limit_usd": 4.0,
        "cap_tier": "c1",
        "include_next_turn_estimate": True,
    }
    reloaded = GatewayConfig(squilla_router=data["squilla_router"])
    assert reloaded.squilla_router.budget.action == "cap"
    assert reloaded.squilla_router.budget.limit_usd == 4.0
    assert reloaded.squilla_router.budget.cap_tier == "c1"
    assert reloaded.squilla_router.budget.include_next_turn_estimate is True


def test_extra_ignore_tolerates_unknown_budget_keys() -> None:
    # A future/rc-drift key on the budget block is dropped, not rejected.
    budget = RouterBudgetConfig(
        action="warn",
        limit_usd=1.0,
        some_future_budget_knob="whatever",  # type: ignore[call-arg]
    )
    assert budget.limit_usd == 1.0
    assert not hasattr(budget, "some_future_budget_knob")


def test_rc1_shape_router_without_budget_loads_default() -> None:
    # An rc1-era router section knows nothing about the budget block.
    rc1_payload = {"enabled": True, "rollout_phase": "full", "default_tier": "c1"}
    config = SquillaRouterConfig(**rc1_payload)
    assert config.budget.limit_usd is None
    assert config.budget.action == "warn"
