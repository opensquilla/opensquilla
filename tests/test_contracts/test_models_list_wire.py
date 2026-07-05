"""Wire-contract freeze for ``models.list`` RPC rows.

The Web UI model picker and external control clients index into these rows
by key name, so the row shape is a public protocol contract (see CLAUDE.md:
public RPC field names are stable).

- Renaming or removing any frozen key is a contract break and must fail here.
- Adding a key requires deliberately extending the frozen sets in this file —
  that friction is the point: wire additions should be a conscious decision.

The shape is frozen at ``_model_info_to_wire``, the pure row builder the
``models.list`` handler maps over provider results; driving the full handler
would require a live provider selector, which contract tests must not need.
Rows are produced from a fully synthetic ``ModelInfo`` — zero network.
"""

from __future__ import annotations

from opensquilla.gateway.rpc_models import _model_info_to_wire
from opensquilla.provider.types import ModelInfo

MODEL_ROW_KEYS = frozenset({"id", "name", "provider", "contextWindow", "capabilities", "pricing"})
MODEL_PRICING_KEYS = frozenset({"inputPer1k", "outputPer1k"})


def _synthetic_model(**overrides) -> dict:
    kwargs: dict = {
        "provider": "test-provider",
        "model_id": "test-provider/test-model",
        "display_name": "Test Model",
        "context_window": 32_000,
        "supports_tools": True,
        "input_cost_per_1k": 0.001,
        "output_cost_per_1k": 0.002,
    }
    kwargs.update(overrides)
    return ModelInfo(**kwargs).model_dump()


def test_model_row_keys_are_frozen() -> None:
    row = _model_info_to_wire(_synthetic_model())
    assert set(row) == MODEL_ROW_KEYS
    assert set(row["pricing"]) == MODEL_PRICING_KEYS


def test_model_row_values_map_from_model_info() -> None:
    # Field-name mapping (snake_case ModelInfo -> camelCase wire) is part of
    # the contract: clients read contextWindow/pricing.inputPer1k literally.
    row = _model_info_to_wire(_synthetic_model())
    assert row["id"] == "test-provider/test-model"
    assert row["name"] == "Test Model"
    assert row["provider"] == "test-provider"
    assert row["contextWindow"] == 32_000
    assert row["pricing"] == {"inputPer1k": 0.001, "outputPer1k": 0.002}


def test_model_row_capability_strings_are_frozen() -> None:
    # Capability strings are matched verbatim by the handler's
    # ``capabilities`` filter and by client-side capability badges.
    with_tools = _model_info_to_wire(_synthetic_model())
    assert with_tools["capabilities"] == ["chat", "tools"]

    without_tools = _model_info_to_wire(_synthetic_model(supports_tools=False))
    assert without_tools["capabilities"] == ["chat"]


def test_model_row_name_falls_back_to_the_model_id() -> None:
    # Clients rely on ``name`` always being renderable even when a provider
    # returns no display name.
    row = _model_info_to_wire(_synthetic_model(display_name=""))
    assert row["name"] == "test-provider/test-model"
