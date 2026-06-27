"""Contract tests for the unified web-search result-count semantics.

These pin the behaviour established by the single-source-of-truth refactor:

* the run-budget clamp is a *pure ceiling* — it never injects a default when the
  caller omits ``max_results``, so the configured ``search_max_results`` governs
  the agent's no-argument searches instead of being silently overridden;
* the gateway config field is bounded to ``[1, MAX_SEARCH_RESULTS]``;
* ``run_web_discover_payload`` clamps to ``MAX_SEARCH_RESULTS`` at the provider
  boundary, so an out-of-range active value cannot ask an uncapped provider
  (e.g. duckduckgo) for an unbounded number of results.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

import opensquilla.search.registry as registry_module
import opensquilla.tools.builtin.web as web_module
from opensquilla.gateway.config import GatewayConfig
from opensquilla.result_budget import ToolRunBudgetPolicy, clamp_tool_arguments
from opensquilla.search.types import DEFAULT_SEARCH_MAX_RESULTS, MAX_SEARCH_RESULTS


@pytest.mark.parametrize("tool", ["web_search", "web_discover"])
def test_clamp_does_not_inject_default_when_absent(tool: str) -> None:
    # The cap must not masquerade as a default: an absent max_results stays
    # absent so the handler's configured fallback governs.
    clamped = clamp_tool_arguments(
        tool, {"query": "q"}, ToolRunBudgetPolicy(max_web_search_results=8)
    )
    assert "max_results" not in clamped


@pytest.mark.parametrize("tool", ["web_search", "web_discover"])
def test_clamp_is_ceiling_only(tool: str) -> None:
    policy = ToolRunBudgetPolicy(max_web_search_results=8)
    # within the cap -> preserved verbatim
    assert (
        clamp_tool_arguments(tool, {"query": "q", "max_results": 3}, policy)[
            "max_results"
        ]
        == 3
    )
    # above the cap -> clamped down
    assert (
        clamp_tool_arguments(tool, {"query": "q", "max_results": 50}, policy)[
            "max_results"
        ]
        == 8
    )


def test_config_field_default_and_bounds() -> None:
    assert GatewayConfig().search_max_results == DEFAULT_SEARCH_MAX_RESULTS
    assert (
        GatewayConfig(search_max_results=MAX_SEARCH_RESULTS).search_max_results
        == MAX_SEARCH_RESULTS
    )
    for out_of_range in (0, MAX_SEARCH_RESULTS + 1):
        with pytest.raises(ValidationError):
            GatewayConfig(search_max_results=out_of_range)


class _RecordingProvider:
    """Minimal SearchProvider stand-in that records the requested count."""

    def __init__(self) -> None:
        self.received: int | None = None

    async def search(self, query: str, max_results: int = 5) -> list:
        self.received = max_results
        return []


@pytest.mark.asyncio
async def test_web_discover_no_arg_uses_configured_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _RecordingProvider()
    monkeypatch.setattr(registry_module, "get_provider", lambda *a, **k: fake)
    web_module.configure_search("duckduckgo", max_results=5)
    try:
        await web_module.run_web_discover_payload("python release")
    finally:
        web_module.configure_search("duckduckgo")
    assert fake.received == 5


@pytest.mark.asyncio
async def test_web_discover_clamps_active_value_to_ceiling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _RecordingProvider()
    monkeypatch.setattr(registry_module, "get_provider", lambda *a, **k: fake)
    # configure_search itself does not bound the value; the provider-boundary
    # clamp in run_web_discover_payload is the defence in depth under test.
    web_module.configure_search("duckduckgo", max_results=MAX_SEARCH_RESULTS + 50)
    try:
        await web_module.run_web_discover_payload("python release")
    finally:
        web_module.configure_search("duckduckgo")
    assert fake.received == MAX_SEARCH_RESULTS


@pytest.mark.asyncio
async def test_web_discover_clamps_explicit_out_of_range_args(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _RecordingProvider()
    monkeypatch.setattr(registry_module, "get_provider", lambda *a, **k: fake)
    web_module.configure_search("duckduckgo", max_results=10)
    try:
        await web_module.run_web_discover_payload("python release", max_results=-5)
        assert fake.received == 1
        await web_module.run_web_discover_payload("python release", max_results=999)
        assert fake.received == MAX_SEARCH_RESULTS
    finally:
        web_module.configure_search("duckduckgo")


def test_migration_coerces_legacy_out_of_range() -> None:
    # A pre-bound config could persist values outside [1, MAX_SEARCH_RESULTS];
    # migration must coerce them so strict GatewayConfig validation does not crash
    # the load.
    from opensquilla.gateway.config_migration import migrate_config_payload

    assert (
        migrate_config_payload({"search_max_results": 50}).payload["search_max_results"]
        == MAX_SEARCH_RESULTS
    )
    assert (
        migrate_config_payload({"search_max_results": 0}).payload["search_max_results"]
        == 1
    )
    assert (
        migrate_config_payload({"search_max_results": "30"}).payload[
            "search_max_results"
        ]
        == MAX_SEARCH_RESULTS
    )
    # in-range values pass through untouched
    assert (
        migrate_config_payload(
            {"search_max_results": DEFAULT_SEARCH_MAX_RESULTS}
        ).payload["search_max_results"]
        == DEFAULT_SEARCH_MAX_RESULTS
    )
