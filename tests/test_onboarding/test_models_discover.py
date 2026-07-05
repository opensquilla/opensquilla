"""Behavior tests for live model discovery (offline, stubbed transport)."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

from opensquilla.gateway import rpc_onboarding
from opensquilla.gateway.config import GatewayConfig, LlmProviderConfig
from opensquilla.gateway.rpc import RpcContext
from opensquilla.onboarding.probe import discover_provider_models
from opensquilla.provider.failures import ProviderFailureKind


def _patch_response(monkeypatch: Any, response_factory) -> list[httpx.Request]:
    """Route provider HTTP through a MockTransport, capturing requests."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return response_factory()

    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    def patched_async_client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr("opensquilla.provider.openai.httpx.AsyncClient", patched_async_client)
    return seen


def _models_response() -> httpx.Response:
    return httpx.Response(
        200,
        headers={"content-type": "application/json"},
        content=json.dumps(
            {"data": [{"id": "test-model-a", "name": "Test Model A", "context_length": 64_000}]}
        ).encode(),
    )


def _discover(**kwargs: Any):
    return asyncio.run(discover_provider_models(**kwargs))


def test_discover_reports_missing_key_without_network(monkeypatch: Any) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    result = _discover(provider_id="openai")
    assert result.ok is False
    assert result.failure_kind == ProviderFailureKind.AUTH_INVALID.value
    assert "OPENAI_API_KEY" in result.detail
    assert result.models == []


def test_discover_rejects_unknown_provider_as_validation_error() -> None:
    with pytest.raises(ValueError, match="Unknown provider"):
        _discover(provider_id="no-such-provider")


def test_discover_reports_build_failure_as_bad_request() -> None:
    # vllm requires an explicit base_url; building without one is a
    # configuration-shaped failure, not transport noise.
    result = _discover(provider_id="vllm", base_url="")
    assert result.ok is False
    assert result.failure_kind == ProviderFailureKind.BAD_REQUEST.value
    assert "base_url" in result.detail


def test_discover_lists_models_with_explicit_key(monkeypatch: Any) -> None:
    seen = _patch_response(monkeypatch, _models_response)
    result = _discover(provider_id="openai", api_key="sk-explicit")
    assert result.ok is True
    assert result.source == "live"
    assert [m["id"] for m in result.models] == ["test-model-a"]
    assert seen[0].headers["authorization"] == "Bearer sk-explicit"


def test_discover_resolves_key_from_provider_env(monkeypatch: Any) -> None:
    # Mirrors the probe: an unset explicit key falls back to the provider's
    # registry env key.
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
    seen = _patch_response(monkeypatch, _models_response)
    result = _discover(provider_id="openai")
    assert result.ok is True
    assert seen[0].headers["authorization"] == "Bearer sk-from-env"


async def test_discover_rpc_reuses_stored_credentials_when_blank(
    tmp_path, monkeypatch: Any
) -> None:
    """Blank credentials on the RPC reuse the stored config's for the same
    provider — upsert_llm_provider's "leave blank to keep current" semantics."""
    seen = _patch_response(monkeypatch, _models_response)
    cfg = GatewayConfig(
        config_path=str(tmp_path / "opensquilla.toml"),
        llm=LlmProviderConfig(provider="openai", model="m", api_key="sk-stored"),
    )
    ctx = RpcContext(conn_id="t", config=cfg)

    payload = await rpc_onboarding._models_discover({"providerId": "openai"}, ctx)

    assert payload["ok"] is True
    assert seen[0].headers["authorization"] == "Bearer sk-stored"


async def test_discover_rpc_does_not_leak_stored_credentials_across_providers(
    tmp_path, monkeypatch: Any
) -> None:
    # The keep-current fallback is provider-bound: discovering a DIFFERENT
    # provider with blank credentials must not send the stored key.
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    cfg = GatewayConfig(
        config_path=str(tmp_path / "opensquilla.toml"),
        llm=LlmProviderConfig(provider="openai", model="m", api_key="sk-stored"),
    )
    ctx = RpcContext(conn_id="t", config=cfg)

    payload = await rpc_onboarding._models_discover({"providerId": "deepseek"}, ctx)

    assert payload["ok"] is False
    assert payload["failureKind"] == ProviderFailureKind.AUTH_INVALID.value


async def test_discover_rpc_explicit_credentials_override_stored(
    tmp_path, monkeypatch: Any
) -> None:
    seen = _patch_response(monkeypatch, _models_response)
    cfg = GatewayConfig(
        config_path=str(tmp_path / "opensquilla.toml"),
        llm=LlmProviderConfig(provider="openai", model="m", api_key="sk-stored"),
    )
    ctx = RpcContext(conn_id="t", config=cfg)

    payload = await rpc_onboarding._models_discover(
        {"providerId": "openai", "apiKey": "sk-candidate"}, ctx
    )

    assert payload["ok"] is True
    assert seen[0].headers["authorization"] == "Bearer sk-candidate"
