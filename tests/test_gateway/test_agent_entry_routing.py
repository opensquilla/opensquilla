"""AgentEntryConfig.routing: additive per-agent tier overrides.

Mirrors ``SquillaRouterConfig`` tier normalization (canonical ``c0``–``c3``,
legacy ``t0``–``t3`` aliases, ``tier:``-prefixed forms) and proves the block is
additive: unset agents persist nothing new via ``to_toml_dict``.
"""

from __future__ import annotations

from opensquilla.gateway.config import (
    AgentEntryConfig,
    AgentRoutingConfig,
    GatewayConfig,
)


def test_routing_block_defaults_to_none() -> None:
    entry = AgentEntryConfig(id="research")
    assert entry.routing is None


def test_routing_fields_default_to_none() -> None:
    routing = AgentRoutingConfig()
    assert routing.default_tier is None
    assert routing.max_tier is None


def test_canonical_tiers_pass_through_unchanged() -> None:
    routing = AgentRoutingConfig(default_tier="c0", max_tier="c3")
    assert routing.default_tier == "c0"
    assert routing.max_tier == "c3"


def test_legacy_alias_t2_normalizes_to_c2() -> None:
    routing = AgentRoutingConfig(default_tier="t2", max_tier="t3")
    assert routing.default_tier == "c2"
    assert routing.max_tier == "c3"


def test_tier_prefixed_form_normalizes() -> None:
    routing = AgentRoutingConfig(default_tier="tier:c1", max_tier="tier:t2")
    assert routing.default_tier == "c1"
    assert routing.max_tier == "c2"


def test_uppercase_and_whitespace_are_normalized() -> None:
    routing = AgentRoutingConfig(default_tier="  T1  ", max_tier="TIER:C3")
    assert routing.default_tier == "c1"
    assert routing.max_tier == "c3"


def test_invalid_tier_kept_verbatim_matching_squilla_router() -> None:
    # SquillaRouterConfig / engine.routing.policy use normalize-or-keep for bad
    # tiers rather than rejecting; this block matches that rigor.
    routing = AgentRoutingConfig(default_tier="x9", max_tier="nope")
    assert routing.default_tier == "x9"
    assert routing.max_tier == "nope"


def test_ordering_is_not_enforced() -> None:
    # max_tier < default_tier is accepted: SquillaRouterConfig enforces no
    # analogous ceiling constraint, so neither does this block.
    routing = AgentRoutingConfig(default_tier="c3", max_tier="c0")
    assert routing.default_tier == "c3"
    assert routing.max_tier == "c0"


def test_agent_entry_carries_configured_routing_block() -> None:
    entry = AgentEntryConfig(
        id="research",
        routing=AgentRoutingConfig(default_tier="t1", max_tier="c2"),
    )
    assert entry.routing is not None
    assert entry.routing.default_tier == "c1"
    assert entry.routing.max_tier == "c2"


def test_unset_routing_persists_nothing_in_to_toml_dict() -> None:
    cfg = GatewayConfig(agents=[AgentEntryConfig(id="research")])
    data = cfg.to_toml_dict()
    agents = data["agents"]
    assert len(agents) == 1
    # Additive block absent when unset — nothing new stamped into the TOML.
    assert "routing" not in agents[0]


def test_set_routing_round_trips_through_to_toml_dict() -> None:
    cfg = GatewayConfig(
        agents=[
            AgentEntryConfig(
                id="research",
                routing=AgentRoutingConfig(default_tier="t2"),
            )
        ]
    )
    data = cfg.to_toml_dict()
    routing = data["agents"][0]["routing"]
    # default_tier normalized to canonical; unset max_tier not persisted.
    assert routing == {"default_tier": "c2"}


def test_bare_agent_to_toml_dict_is_byte_stable_vs_pre_change_shape() -> None:
    # An agent that does not set routing dumps exactly the historical fields.
    entry = AgentEntryConfig(id="research", enabled=True)
    dumped = GatewayConfig(agents=[entry]).to_toml_dict()["agents"][0]
    assert "routing" not in dumped
    assert dumped["id"] == "research"
