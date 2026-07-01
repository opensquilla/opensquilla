"""Single implementation of applying a per-turn model to a cloned selector.

Two turn-path sites apply a model override — the pipeline tail applies the
*routed* model, PromptAssemblerStage applies an *explicit* per-turn model on
top of it. They previously carried textually near-identical blocks that had
already drifted once (the routed_model telemetry realignment existed only in
the stage copy). The mechanics live here exactly once.
"""

from __future__ import annotations

from typing import Any

_ROUTE_SAVINGS_KEYS = (
    "savings_pct",
    "savings_max_price_per_m",
    "savings_routed_price_per_m",
)


def apply_model_override(
    selector: Any,
    model: str,
    *,
    turn_metadata: dict[str, Any],
    realign_routed_model: bool,
) -> Any:
    """Apply ``model`` to the cloned selector and resolve the provider.

    ``realign_routed_model`` is True only for the explicit-override site: an
    explicit model replaces the routed choice, so ``routed_model`` (read by
    RouterDecisionEvent and comprehensive-savings pricing) must follow and the
    route-savings figures no longer apply. The routed-model site must NOT
    realign — in observe rollout phase the baseline model runs while
    ``routed_model`` intentionally records the would-be routed choice.
    """
    router_fallback_chain = (
        turn_metadata.get("router_fallback_chain")
        if turn_metadata.get("routing_applied") is True
        else None
    )
    override_with_fallback_chain = getattr(
        selector,
        "override_model_with_fallback_chain",
        None,
    )
    if callable(override_with_fallback_chain) and isinstance(router_fallback_chain, list):
        override_with_fallback_chain(model, router_fallback_chain)
    else:
        selector.override_model(model)
    provider = selector.resolve()

    if realign_routed_model and turn_metadata.get("routed_model") not in (None, model):
        turn_metadata["routed_model"] = model
        for savings_key in _ROUTE_SAVINGS_KEYS:
            if savings_key in turn_metadata:
                turn_metadata[savings_key] = 0.0
    return provider
