"""Regression tests for the version + provider readouts in gateway status surfaces.

Pins two fixes:
  * The displayed version derives from installed package metadata
    (``importlib.metadata``) rather than a hardcoded literal that silently
    goes stale — it had been frozen at ``"0.1.0"`` across config, the status
    RPC, and gateway identity while the package was at 0.2.1.
  * The provider readout reports the *configured* provider id (e.g.
    ``"openrouter"``), not the OpenAI-compatible backend class that physically
    serves it. OpenRouter/DeepSeek/Gemini all run through ``OpenAIProvider``,
    so introspecting the instance used to mislabel them as ``"openai"``.
"""

from __future__ import annotations

from importlib.metadata import version as _pkg_version
from types import SimpleNamespace

import pytest

import opensquilla
from opensquilla.gateway.rpc.registry import RpcContext, _gateway_identity_get, _status
from opensquilla.provider.selector import ModelSelector, ProviderConfig, SelectorConfig


def _ctx(**kwargs: object) -> RpcContext:
    return RpcContext(conn_id="c", principal=SimpleNamespace(role="operator"), **kwargs)


def _openrouter_selector() -> ModelSelector:
    return ModelSelector(
        SelectorConfig(
            primary=ProviderConfig(provider="openrouter", model="deepseek/deepseek-v4-flash")
        )
    )


def test_package_version_tracks_metadata_not_stale_literal() -> None:
    assert opensquilla.__version__ == _pkg_version("opensquilla")
    assert opensquilla.__version__ != "0.1.0"


def test_active_provider_id_reports_configured_id() -> None:
    assert _openrouter_selector().active_provider_id == "openrouter"


def test_active_provider_id_follows_failover() -> None:
    sel = ModelSelector(
        SelectorConfig(
            primary=ProviderConfig(provider="openrouter", model="m"),
            fallbacks=[ProviderConfig(provider="anthropic", model="claude")],
        )
    )
    assert sel.active_provider_id == "openrouter"
    sel.next_fallback()
    assert sel.active_provider_id == "anthropic"


@pytest.mark.asyncio
async def test_status_rpc_reports_metadata_version_and_configured_provider() -> None:
    result = await _status(None, _ctx(provider_selector=_openrouter_selector()))
    assert result["version"] == opensquilla.__version__
    # Configured id surfaced — NOT the "OpenAIProvider" backend class / "openai".
    assert result["provider"] == "openrouter"


@pytest.mark.asyncio
async def test_status_rpc_provider_is_none_without_selector() -> None:
    result = await _status(None, _ctx(provider_selector=None))
    assert result["provider"] is None
    assert result["version"] == opensquilla.__version__


@pytest.mark.asyncio
async def test_gateway_identity_reports_metadata_version() -> None:
    result = await _gateway_identity_get(None, _ctx())
    assert result["version"] == opensquilla.__version__
