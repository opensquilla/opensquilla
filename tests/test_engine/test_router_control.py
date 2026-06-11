from __future__ import annotations

import copy
import json
from types import SimpleNamespace

import pytest

from opensquilla.engine.pipeline import TurnContext
from opensquilla.engine.steps.squilla_router import apply_squilla_router
from opensquilla.gateway.config import (
    ROUTER_TIER_PROFILE_IDS,
    SquillaRouterConfig,
    _router_tier_profile_defaults,
)
from opensquilla.router_control import (
    RouterControlHoldStore,
    RouterControlValidationError,
    build_router_control_targets,
    render_router_control_prompt_block,
    render_router_control_status_prompt,
    resolve_router_control_target,
)


def _router_cfg(tiers: dict) -> SquillaRouterConfig:
    return SquillaRouterConfig(
        enabled=True,
        rollout_phase="full",
        require_router_runtime=False,
        auto_thinking=False,
        tiers=tiers,
        default_tier="c1" if "c1" in tiers else next(iter(tiers)),
    )


def test_router_control_targets_generalize_to_every_profile() -> None:
    for profile in sorted(ROUTER_TIER_PROFILE_IDS):
        tiers = _router_tier_profile_defaults(profile)
        targets = build_router_control_targets(_router_cfg(tiers))
        target_ids = {target.target_id for target in targets}

        for tier_name, tier_cfg in tiers.items():
            if tier_cfg.get("image_only"):
                assert f"tier:{tier_name}" not in target_ids
                continue
            assert f"tier:{tier_name}" in target_ids


def test_model_targets_are_rejected_by_local_validation() -> None:
    cfg = _router_cfg(
        {
            "c0": {"provider": "openrouter", "model": "same/model", "supports_image": False},
            "c1": {"provider": "openrouter", "model": "other/model", "supports_image": False},
            "c3": {"provider": "openrouter", "model": "same/model", "supports_image": False},
        }
    )

    with pytest.raises(RouterControlValidationError):
        resolve_router_control_target(cfg, "model:same/model")


def test_natural_language_aliases_are_rejected_by_local_validation() -> None:
    cfg = _router_cfg(_router_tier_profile_defaults("openrouter"))

    with pytest.raises(RouterControlValidationError):
        resolve_router_control_target(cfg, "Claude Opus 4.7")


def test_legacy_tier_target_aliases_resolve_to_canonical_routes() -> None:
    cfg = _router_cfg(_router_tier_profile_defaults("openrouter"))

    target = resolve_router_control_target(cfg, "tier:t3")

    assert target.target_id == "tier:c3"
    assert target.tier == "c3"


def test_hold_store_expires_by_explicit_turn_count_and_sliding_idle_time() -> None:
    cfg = _router_cfg(_router_tier_profile_defaults("openrouter"))
    target = resolve_router_control_target(cfg, "tier:c3")
    store = RouterControlHoldStore()
    store.set_hold(
        "agent:main:test",
        target,
        evidence="use c3",
        now_monotonic=100.0,
        turns_remaining=1,
        ttl_seconds=10.0,
    )

    first = store.get_valid("agent:main:test", now_monotonic=101.0, decrement=True)
    assert first is not None
    assert first.tier == "c3"
    assert store.get_valid("agent:main:test", now_monotonic=102.0) is None

    store.set_hold(
        "agent:main:test",
        target,
        evidence="use c3 again",
        now_monotonic=100.0,
        ttl_seconds=10.0,
    )
    assert store.get_valid("agent:main:test", now_monotonic=109.0, decrement=True) is not None
    assert store.get_valid("agent:main:test", now_monotonic=118.0) is not None
    assert store.get_valid("agent:main:test", now_monotonic=119.0) is None


def test_hold_store_deepcopy_preserves_session_identity_for_ttl_refresh() -> None:
    cfg = _router_cfg(_router_tier_profile_defaults("openrouter"))
    target = resolve_router_control_target(cfg, "tier:c3")
    store = RouterControlHoldStore()
    store.set_hold(
        "agent:main:test",
        target,
        evidence="use c3",
        now_monotonic=100.0,
        ttl_seconds=10.0,
    )

    copied = copy.deepcopy(store)

    assert copied is store
    assert copied.get_valid("agent:main:test", now_monotonic=109.0, decrement=True) is not None
    assert store.get_valid("agent:main:test", now_monotonic=118.0) is not None
    assert store.get_valid("agent:main:test", now_monotonic=119.0) is None


@pytest.mark.asyncio
async def test_squilla_router_refreshes_hold_idle_ttl_through_copied_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = _router_cfg(_router_tier_profile_defaults("openrouter"))
    target = resolve_router_control_target(cfg, "tier:c3")
    store = RouterControlHoldStore()
    store.set_hold(
        "agent:main:test-refresh",
        target,
        evidence="use c3",
        now_monotonic=100.0,
        ttl_seconds=10.0,
    )
    now = [109.0]
    monkeypatch.setattr("opensquilla.router_control.time.monotonic", lambda: now[0])

    metadata = copy.deepcopy({"router_control_hold_store": store})
    ctx = TurnContext(
        message="continue this",
        session_key="agent:main:test-refresh",
        config=SimpleNamespace(squilla_router=cfg),
        provider=None,
        model="default-model",
        tool_defs=[],
        system_prompt="system",
        metadata=metadata,
    )

    out = await apply_squilla_router(ctx)

    assert out.metadata["routing_source"] == "router_control_hold"
    now[0] = 118.0
    assert store.get_valid("agent:main:test-refresh") is not None
    now[0] = 119.0
    assert store.get_valid("agent:main:test-refresh") is None


@pytest.mark.asyncio
async def test_squilla_router_applies_hold_before_normal_classification(monkeypatch) -> None:
    cfg = _router_cfg(_router_tier_profile_defaults("openrouter"))
    target = resolve_router_control_target(cfg, "tier:c3")
    store = RouterControlHoldStore()
    store.set_hold("agent:main:test", target, evidence="use c3")

    def fail_strategy(_cfg: object) -> object:
        raise AssertionError("router classification should not run while hold is valid")

    monkeypatch.setattr("opensquilla.engine.steps.squilla_router._get_strategy", fail_strategy)
    ctx = TurnContext(
        message="review this",
        session_key="agent:main:test",
        config=SimpleNamespace(squilla_router=cfg),
        provider=None,
        model="default-model",
        tool_defs=[],
        system_prompt="system",
        metadata={"router_control_hold_store": store},
    )

    out = await apply_squilla_router(ctx)

    assert out.model == "anthropic/claude-opus-4.7"
    assert out.metadata["routing_source"] == "router_control_hold"
    assert out.metadata["router_control_hold_applied"] is True
    assert out.metadata["router_control_target_id"] == "tier:c3"
    assert out.metadata["router_control_target_tier"] == "c3"


@pytest.mark.asyncio
async def test_squilla_router_records_routed_provider_from_tier(monkeypatch) -> None:
    class _Strategy:
        async def classify(self, *_args, **_kwargs):
            return "c2", 0.91, "test_strategy", {}

    monkeypatch.setattr(
        "opensquilla.engine.steps.squilla_router._get_strategy",
        lambda _cfg: _Strategy(),
    )
    cfg = _router_cfg(
        {
            "c1": {
                "provider": "inception",
                "model": "inception/mercury-2",
                "supports_image": False,
            },
            "c2": {
                "provider": "openrouter",
                "model": "z-ai/glm-5.1",
                "supports_image": False,
            },
        }
    )
    ctx = TurnContext(
        message="hard reasoning question",
        session_key="agent:main:test-provider-route",
        config=SimpleNamespace(squilla_router=cfg),
        provider=None,
        model="inception/mercury-2",
        tool_defs=[],
        system_prompt="system",
        metadata={},
    )

    out = await apply_squilla_router(ctx)

    assert out.model == "z-ai/glm-5.1"
    assert out.metadata["routed_tier"] == "c2"
    assert out.metadata["routed_model"] == "z-ai/glm-5.1"
    assert out.metadata["routed_provider"] == "openrouter"


@pytest.mark.asyncio
async def test_image_attachments_bypass_text_hold(monkeypatch) -> None:
    cfg = _router_cfg(_router_tier_profile_defaults("openrouter"))
    target = resolve_router_control_target(cfg, "tier:c3")
    store = RouterControlHoldStore()
    store.set_hold("agent:main:test-image", target, evidence="use c3")

    def fail_strategy(_cfg: object) -> object:
        raise AssertionError("image route should not classify")

    monkeypatch.setattr("opensquilla.engine.steps.squilla_router._get_strategy", fail_strategy)
    ctx = TurnContext(
        message="what is in this image?",
        session_key="agent:main:test-image",
        config=SimpleNamespace(squilla_router=cfg),
        provider=None,
        model="default-model",
        tool_defs=[],
        system_prompt="system",
        attachments=[{"mime": "image/png"}],
        metadata={"router_control_hold_store": store},
    )

    out = await apply_squilla_router(ctx)

    assert out.metadata["routing_source"] == "image_route"
    assert out.metadata.get("router_control_hold_applied") is not True
    assert out.model == "moonshotai/kimi-k2.6"


def test_prompt_block_exposes_provider_model_mapping_without_descriptions() -> None:
    cfg = _router_cfg(
        {
            "c0": {
                "provider": "inception",
                "model": "inception/mercury-2",
                "description": "Mercury diffusion route",
                "supports_image": False,
            },
            "c1": {
                "provider": "openai_compatible",
                "model": "inclusionAI/LLaDA2.1-flash",
                "description": "Self-hosted LLaDA route",
                "supports_image": False,
            },
        }
    )

    block = render_router_control_prompt_block(cfg)
    menu = json.loads(block.split("router_control_targets=", 1)[1])

    assert "router_control" in block
    assert {
        "target_id": "tier:c0",
        "provider": "inception",
        "model": "inception/mercury-2",
    } in menu
    assert {
        "target_id": "tier:c1",
        "provider": "openai_compatible",
        "model": "inclusionAI/LLaDA2.1-flash",
    } in menu
    assert all("label" not in row for row in menu)
    assert all("description" not in row for row in menu)
    assert "tier:t3" not in block
    assert "Mercury diffusion route" not in block
    assert "description" not in block
    assert "thinking_level" not in block
    assert "same provider/model" in block
    assert "must choose one target_id exactly" in block


def test_router_control_status_prompt_renders_only_after_hold_applied() -> None:
    assert render_router_control_status_prompt({}) == ""
    assert (
        render_router_control_status_prompt(
            {
                "router_control_hold_applied": False,
                "router_control_target_id": "tier:c1",
            }
        )
        == ""
    )

    block = render_router_control_status_prompt(
        {
            "router_control_hold_applied": True,
            "router_control_target_id": "tier:c1",
            "router_control_target_provider": "openai_compatible",
            "router_control_target_model": "inclusionAI/LLaDA2.1-flash",
        }
    )

    assert "Router Control status" in block
    assert "target_id=tier:c1" in block
    assert "provider=openai_compatible" in block
    assert "model=inclusionAI/LLaDA2.1-flash" in block
    assert "Do not call router_control again" in block
