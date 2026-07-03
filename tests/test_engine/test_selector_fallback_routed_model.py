"""Failover must realign routed_model telemetry to the model that runs.

Same invariant the explicit-model override realignment enforces
(prompt_assembler_stage, commit 966df982): ``metadata["routed_model"]`` is
read by RouterDecisionEvent and comprehensive-savings pricing, so after a
selector failover it must name the fallback model, and route-savings figures
computed for the abandoned model no longer apply.
"""

from __future__ import annotations

from types import SimpleNamespace

from opensquilla.engine.runtime import _SelectorFallbackProvider


class _StubSelector:
    def __init__(self, fallback_model: str) -> None:
        self._fallback_model = fallback_model

    def next_fallback_after_failure(self, exc: Exception) -> object:
        return object()

    @property
    def current_config(self) -> SimpleNamespace:
        return SimpleNamespace(model=self._fallback_model)


def test_fallback_realigns_routed_model_and_drops_savings() -> None:
    metadata: dict[str, object] = {
        "routed_model": "expensive/model",
        "savings_pct": 12.5,
        "savings_max_price_per_m": 3.0,
        "savings_routed_price_per_m": 0.5,
    }
    wrapper = _SelectorFallbackProvider(
        object(),
        _StubSelector("cheap/fallback"),
        turn_metadata=metadata,
    )

    assert wrapper.fallback_after_invalid_response("upstream 503") is True

    assert metadata["routed_model"] == "cheap/fallback"
    assert metadata["savings_pct"] == 0.0
    assert metadata["savings_max_price_per_m"] == 0.0
    assert metadata["savings_routed_price_per_m"] == 0.0


def test_fallback_to_same_model_keeps_savings() -> None:
    metadata: dict[str, object] = {"routed_model": "same/model", "savings_pct": 7.0}
    wrapper = _SelectorFallbackProvider(
        object(),
        _StubSelector("same/model"),
        turn_metadata=metadata,
    )

    assert wrapper.fallback_after_invalid_response("upstream 503") is True

    assert metadata["routed_model"] == "same/model"
    assert metadata["savings_pct"] == 7.0


def test_fallback_without_metadata_is_noop() -> None:
    wrapper = _SelectorFallbackProvider(object(), _StubSelector("any/model"))
    assert wrapper.fallback_after_invalid_response("upstream 503") is True
