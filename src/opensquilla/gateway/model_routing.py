"""Canonical Gateway-owned model-routing mode contract.

The WebUI historically derived the effective ``direct | router | ensemble``
mode from three config fields. Keep that policy in the Gateway so every
surface observes and mutates the same state machine.
"""

from __future__ import annotations

import copy
from typing import Any, Literal

ModelRoutingMode = Literal["direct", "router", "ensemble"]

_INDEPENDENT_ENSEMBLE_MODES = frozenset(
    {"static_openrouter_b5", "static_tokenrhythm_b5", "custom_b5"}
)


def _clean(value: object) -> str:
    return str(value or "").strip().lower()


def model_routing_snapshot(config: Any) -> dict[str, Any]:
    """Return the additive public snapshot for the current runtime strategy."""

    router = getattr(config, "squilla_router", None)
    ensemble = getattr(config, "llm_ensemble", None)
    router_enabled = bool(getattr(router, "enabled", False))
    ensemble_enabled = bool(getattr(ensemble, "enabled", False))
    rollout_phase = _clean(getattr(router, "rollout_phase", "observe")) or "observe"
    selection_mode = _clean(getattr(ensemble, "selection_mode", ""))
    router_required = selection_mode not in _INDEPENDENT_ENSEMBLE_MODES

    if ensemble_enabled:
        mode: ModelRoutingMode = "ensemble"
    elif router_enabled and rollout_phase != "observe":
        mode = "router"
    else:
        mode = "direct"

    return {
        "mode": mode,
        "router_enabled": router_enabled,
        "ensemble_enabled": ensemble_enabled,
        "rollout_phase": rollout_phase,
        "selection_mode": selection_mode,
        "router_required_by_ensemble": router_required,
        "applies_to": "next_accepted_turn",
    }


def model_routing_patches(config: Any, mode: str) -> dict[str, Any]:
    """Translate one public mode into the persisted config patch contract."""

    normalized = _clean(mode)
    if normalized not in {"direct", "router", "ensemble"}:
        raise ValueError("params.mode must be direct, router, or ensemble")

    if normalized == "direct":
        return {
            "llm_ensemble.enabled": False,
            "squilla_router.enabled": False,
            "squilla_router.rollout_phase": "observe",
        }
    if normalized == "router":
        return {
            "llm_ensemble.enabled": False,
            "squilla_router.enabled": True,
            "squilla_router.rollout_phase": "full",
        }

    selection_mode = _clean(
        getattr(getattr(config, "llm_ensemble", None), "selection_mode", "")
    )
    return {
        "llm_ensemble.enabled": True,
        "squilla_router.enabled": selection_mode not in _INDEPENDENT_ENSEMBLE_MODES,
        "squilla_router.rollout_phase": "full",
    }


def capture_model_routing_config(config: Any) -> Any:
    """Freeze model-routing inputs at the turn acceptance boundary.

    Gateway config writes update the long-lived config object in place.  A
    queued/running turn must not observe a half-new strategy merely because a
    surface switches ``direct | router | ensemble`` while that turn is being
    prepared.  Keep a shallow config clone (so unrelated runtime services retain
    their established references) and deep-copy only the two routing subtrees
    whose values the control plane can mutate live.
    """

    if config is None:
        return None
    router = copy.deepcopy(getattr(config, "squilla_router", None))
    ensemble = copy.deepcopy(getattr(config, "llm_ensemble", None))
    model_copy = getattr(config, "model_copy", None)
    if callable(model_copy):
        return model_copy(
            update={
                "squilla_router": router,
                "llm_ensemble": ensemble,
            },
            deep=False,
        )
    snapshot = copy.copy(config)
    setattr(snapshot, "squilla_router", router)
    setattr(snapshot, "llm_ensemble", ensemble)
    return snapshot


async def broadcast_model_routing_changed(ctx: Any, *, source: str) -> dict[str, Any]:
    """Broadcast the canonical snapshot to every readable operator surface."""

    snapshot = model_routing_snapshot(getattr(ctx, "config", None))
    payload = {**snapshot, "source": source}
    subscription_manager = getattr(ctx, "subscription_manager", None)
    if subscription_manager is None:
        return payload

    # Local imports avoid making websocket boot order part of config loading.
    from opensquilla.gateway.event_bridge import EventBridge
    from opensquilla.gateway.scopes import READ_SCOPE
    from opensquilla.gateway.websocket import get_registry

    await EventBridge(subscription_manager, get_registry()).broadcast_scoped(
        "models.routing.changed",
        payload,
        required_scope=READ_SCOPE,
    )
    return payload


__all__ = [
    "ModelRoutingMode",
    "broadcast_model_routing_changed",
    "capture_model_routing_config",
    "model_routing_patches",
    "model_routing_snapshot",
]
