"""Wire-contract freeze for ``models.list`` RPC rows.

The Web UI model picker and external control clients index into these rows
by key name, so the row shape is a public protocol contract (see CLAUDE.md:
public RPC field names are stable).

- Renaming or removing any frozen key is a contract break and must fail here.
- Adding a key requires deliberately extending the frozen sets in this file —
  that friction is the point: wire additions should be a conscious decision.

The row and error shapes are frozen at ``_model_info_to_wire`` /
``_list_error_to_wire``, the pure builders the ``models.list`` handler maps
over selector results; the envelope is frozen by driving the handler with a
fully synthetic in-memory selector stub — zero network either way.
"""

from __future__ import annotations

from opensquilla.gateway.rpc import RpcContext
from opensquilla.gateway.rpc_models import (
    _handle_models_list,
    _list_error_to_wire,
    _model_info_to_wire,
)
from opensquilla.provider.selector import ModelListResult, ProviderListError
from opensquilla.provider.types import ModelInfo

# Additive wire evolution: ``source`` (catalog provenance) and
# ``reasoningFormat`` (reasoning dialect) were added deliberately. Extending
# this frozen set is the conscious decision the friction is meant to force —
# renaming or removing any existing key must still fail here.
MODEL_ROW_KEYS = frozenset(
    {
        "id",
        "name",
        "provider",
        "contextWindow",
        "capabilities",
        "pricing",
        "source",
        "reasoningFormat",
    }
)
MODEL_PRICING_KEYS = frozenset({"inputPer1k", "outputPer1k"})
# Additive top-level envelope key: ``errors`` carries classified, redacted
# per-provider listing failures alongside ``models``. Each error row is frozen
# to exactly these keys.
MODEL_ERROR_KEYS = frozenset({"provider", "kind", "detail"})


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


def test_model_row_carries_catalog_provenance() -> None:
    # A model unknown to every catalog layer still resolves to a synthesized
    # entry, so ``source``/``reasoningFormat`` are always renderable strings.
    row = _model_info_to_wire(_synthetic_model())
    assert isinstance(row["source"], str) and row["source"]
    assert isinstance(row["reasoningFormat"], str) and row["reasoningFormat"]


def test_error_row_keys_are_frozen() -> None:
    err = _list_error_to_wire(
        ProviderListError(
            provider="test-provider",
            model_hint="test-provider/test-model",
            kind="auth_invalid",
            detail="invalid api key",
        )
    )
    assert set(err) == MODEL_ERROR_KEYS
    # ``model_hint`` is selector-internal operator context; it stays off the
    # wire on purpose.
    assert "model_hint" not in err
    assert err == {
        "provider": "test-provider",
        "kind": "auth_invalid",
        "detail": "invalid api key",
    }



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


MODEL_ENVELOPE_KEYS = frozenset({"models", "errors"})


class _StubSelector:
    """Zero-network selector stub returning a fixed ModelListResult."""

    def __init__(self, result: ModelListResult) -> None:
        self._result = result

    async def list_models_detailed(self) -> ModelListResult:
        return self._result


async def test_models_list_envelope_keys_are_frozen() -> None:
    result = ModelListResult(
        models=[_synthetic_model()],
        errors=[
            ProviderListError(
                provider="test-provider",
                model_hint="test-provider/test-model",
                kind="auth_invalid",
                detail="invalid api key",
            )
        ],
    )
    ctx = RpcContext(conn_id="test", provider_selector=_StubSelector(result))
    envelope = await _handle_models_list({}, ctx)

    assert set(envelope) == MODEL_ENVELOPE_KEYS
    assert set(envelope["models"][0]) == MODEL_ROW_KEYS
    assert envelope["errors"] == [
        {"provider": "test-provider", "kind": "auth_invalid", "detail": "invalid api key"}
    ]

