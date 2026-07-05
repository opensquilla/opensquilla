"""Wire-contract freeze for the ``onboarding.models.discover`` RPC payload.

The discover envelope feeds the Web UI model picker during onboarding and any
external control client, so its key names are a public protocol contract (see
CLAUDE.md: public RPC field names are stable). These tests pin today's exact
key sets:

- Renaming or removing any frozen key is a contract break and must fail here.
- Adding a key requires deliberately extending the frozen sets in this file —
  that friction is the point: wire additions should be a conscious decision.

Everything below drives the real RPC handler and the underlying
``discover_provider_models`` against a stubbed httpx transport (the provider
probe's test pattern) — zero network, zero credentials (tests/conftest.py
strips provider keys from the environment; only synthetic keys appear here).
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from opensquilla.gateway import rpc_onboarding
from opensquilla.gateway.config import GatewayConfig
from opensquilla.gateway.rpc import RpcContext
from opensquilla.gateway.scopes import ADMIN_SCOPE, METHOD_SCOPES

# Top-level envelope. ``source`` distinguishes "the provider listed models"
# ("live") from "provider lists nothing / does not support listing" ("none",
# still ok=true); a classified failure is ok=false with failureKind/detail.
DISCOVER_ENVELOPE_KEYS = frozenset({"ok", "failureKind", "detail", "source", "models"})

# Per-model row. ``pricing`` is an object with the frozen keys below or null
# when no layer knows a price; ``capabilitySource`` names the catalog layer
# that resolved the row's metadata (ModelCatalogEntry.source).
DISCOVER_MODEL_ROW_KEYS = frozenset(
    {
        "id",
        "name",
        "contextWindow",
        "maxOutputTokens",
        "capabilities",
        "pricing",
        "capabilitySource",
    }
)
DISCOVER_PRICING_KEYS = frozenset({"inputPer1k", "outputPer1k"})

# A synthetic model id no catalog layer can know, so the row provably falls
# back to the synthesized floor for anything the live listing omits.
_MODELS_BODY: dict[str, Any] = {
    "data": [
        {
            "id": "test-vendor/test-model",
            "name": "Test Model",
            "context_length": 128_000,
            "top_provider": {"max_completion_tokens": 16_384},
        }
    ]
}


def _patch_models_response(monkeypatch: Any, response: httpx.Response) -> None:
    transport = httpx.MockTransport(lambda request: response)
    real_async_client = httpx.AsyncClient

    def patched_async_client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr("opensquilla.provider.openai.httpx.AsyncClient", patched_async_client)


def _ok_models_response() -> httpx.Response:
    return httpx.Response(
        200,
        headers={"content-type": "application/json"},
        content=json.dumps(_MODELS_BODY).encode(),
    )


def _ctx(tmp_path: Any) -> RpcContext:
    # config_path points at a nonexistent tmp file so the handler never reads
    # the developer's real ~/.opensquilla config.
    return RpcContext(
        conn_id="contract",
        config=GatewayConfig(config_path=str(tmp_path / "opensquilla.toml")),
    )


async def test_discover_envelope_keys_are_frozen(tmp_path, monkeypatch: Any) -> None:
    _patch_models_response(monkeypatch, _ok_models_response())

    payload = await rpc_onboarding._models_discover(
        {"providerId": "openai", "apiKey": "sk-test"}, _ctx(tmp_path)
    )

    assert set(payload) == DISCOVER_ENVELOPE_KEYS
    assert payload["ok"] is True
    assert payload["source"] == "live"
    assert payload["models"], "a live listing must produce rows"


async def test_discover_model_row_keys_are_frozen(tmp_path, monkeypatch: Any) -> None:
    _patch_models_response(monkeypatch, _ok_models_response())

    payload = await rpc_onboarding._models_discover(
        {"providerId": "openai", "apiKey": "sk-test"}, _ctx(tmp_path)
    )

    (row,) = payload["models"]
    assert set(row) == DISCOVER_MODEL_ROW_KEYS
    # Field-name mapping is part of the contract: clients index into these
    # camelCase names literally.
    assert row["id"] == "test-vendor/test-model"
    assert row["name"] == "Test Model"
    assert row["contextWindow"] == 128_000
    assert row["maxOutputTokens"] == 16_384
    # Capability strings are matched verbatim by client capability badges.
    assert isinstance(row["capabilities"], list)
    assert "chat" in row["capabilities"]
    # No layer knows this synthetic model's price → pricing is null (a
    # deliberate contrast with models.list, which reports 0.0 for unknown).
    assert row["pricing"] is None
    # Metadata provenance comes from the layered catalog; an unknown model
    # resolves to the synthesized floor rather than failing.
    assert row["capabilitySource"] == "synthesized"


async def test_discover_pricing_keys_are_frozen_when_present(tmp_path, monkeypatch: Any) -> None:
    # Install an isolated shared catalog carrying a known per-Mtok price so
    # the pricing-object branch is exercised deterministically offline (the
    # catalog's user-override layer is the highest resolution authority).
    from opensquilla.provider.model_catalog import ModelCatalog, set_shared_catalog

    catalog = ModelCatalog()
    catalog.set_user_overrides(
        {
            "openai/test-vendor/test-model": {
                "input_cost_per_mtok": 1.0,
                "output_cost_per_mtok": 2.0,
            }
        }
    )
    set_shared_catalog(catalog)
    try:
        _patch_models_response(monkeypatch, _ok_models_response())
        payload = await rpc_onboarding._models_discover(
            {"providerId": "openai", "apiKey": "sk-test"}, _ctx(tmp_path)
        )
    finally:
        set_shared_catalog(None)

    (row,) = payload["models"]
    # Costs are canonical per-Mtok in the catalog; the wire stays per-1k for
    # parity with models.list pricing rows.
    assert set(row["pricing"]) == DISCOVER_PRICING_KEYS
    assert row["pricing"] == {"inputPer1k": 0.001, "outputPer1k": 0.002}
    # capabilitySource names the layer that resolved the entry ("user" here).
    assert row["capabilitySource"] == "user"


async def test_discover_empty_listing_is_ok_with_source_none(tmp_path, monkeypatch: Any) -> None:
    # "Provider lists nothing / does not support listing" is NOT a failure:
    # ok stays true, source is "none", models is empty. Clients must be able
    # to distinguish this from a classified failure (ok=false).
    _patch_models_response(
        monkeypatch,
        httpx.Response(
            200,
            headers={"content-type": "application/json"},
            content=b'{"data": []}',
        ),
    )

    payload = await rpc_onboarding._models_discover(
        {"providerId": "openai", "apiKey": "sk-test"}, _ctx(tmp_path)
    )

    assert set(payload) == DISCOVER_ENVELOPE_KEYS
    assert payload["ok"] is True
    assert payload["source"] == "none"
    assert payload["models"] == []
    assert payload["failureKind"] == ""


async def test_discover_classified_failure_envelope_is_frozen(tmp_path, monkeypatch: Any) -> None:
    """A raising provider produces ok=false with a classified, redacted error."""

    class _RaisingProvider:
        provider_name = "openai"

        async def list_models(self):  # noqa: ANN202 - test stub
            request = httpx.Request("GET", "https://api.openai.com/v1/models")
            response = httpx.Response(
                401,
                request=request,
                content=b'{"error": {"message": "Incorrect API key provided: sk-badkey000"}}',
            )
            raise httpx.HTTPStatusError("401", request=request, response=response)

    monkeypatch.setattr(
        "opensquilla.onboarding.probe.build_provider",
        lambda *args, **kwargs: _RaisingProvider(),
    )

    payload = await rpc_onboarding._models_discover(
        {"providerId": "openai", "apiKey": "sk-test"}, _ctx(tmp_path)
    )

    assert set(payload) == DISCOVER_ENVELOPE_KEYS
    assert payload["ok"] is False
    assert payload["source"] == "none"
    assert payload["models"] == []
    assert payload["failureKind"] == "auth_invalid"
    # detail is redacted free text: never echo credential-shaped material.
    assert "sk-badkey000" not in payload["detail"]


def test_discover_method_is_admin_scoped() -> None:
    # Frozen on purpose: discover accepts candidate credentials in params
    # (like onboarding.provider.probe), so it must never drop below admin.
    assert METHOD_SCOPES["onboarding.models.discover"] == ADMIN_SCOPE
