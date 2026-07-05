"""Doctor advisory for router tiers that will silently misroute.

The warn finding fires only for the risky combination: router enabled, a
configured tier naming a provider other than the active one,
cross_provider_tiers off, and tier_provider_mismatch in "route" mode.
Aligned tiers, cross-provider execution, or veto mode produce no finding.
All provider/tier names are synthetic dummy data.
"""

from __future__ import annotations

from typing import Any

import pytest

from opensquilla.health.evaluator import evaluate_router


def router_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "enabled": True,
        "rolloutPhase": "full",
        "strategy": "v4_phase3",
        "tierProfile": "custom",
        "defaultTier": "c1",
        "runtimeValid": True,
        "requireRouterRuntime": False,
        "runtimeErrorKind": None,
        "activeProvider": "mainprov",
        "crossProviderTiers": False,
        "tierProviderMismatch": "route",
        "mismatchedTierProviders": {"c2": "otherprov"},
    }
    payload.update(overrides)
    return payload


def finding_ids(findings: list[Any]) -> list[str]:
    return [finding.id for finding in findings]


def test_mismatch_advisory_emitted_alongside_ready() -> None:
    findings = evaluate_router(router_payload())
    assert finding_ids(findings) == ["router.ready", "router.tier_provider.mismatch"]
    advisory = findings[1]
    assert advisory.severity == "warn"
    assert advisory.surface == "router"
    assert "misroute" in advisory.detail
    assert "veto" in advisory.detail
    assert advisory.evidence["activeProvider"] == "mainprov"
    assert advisory.evidence["mismatchedTierProviders"] == {"c2": "otherprov"}
    commands = [step.command for step in advisory.fix_steps if step.command]
    assert (
        "opensquilla config set squilla_router.tier_provider_mismatch veto" in commands
    )


def test_no_advisory_when_tiers_align() -> None:
    findings = evaluate_router(router_payload(mismatchedTierProviders={}))
    assert finding_ids(findings) == ["router.ready"]


def test_no_advisory_when_veto_mode_on() -> None:
    findings = evaluate_router(router_payload(tierProviderMismatch="veto"))
    assert finding_ids(findings) == ["router.ready"]


def test_no_advisory_when_cross_provider_execution_enabled() -> None:
    findings = evaluate_router(router_payload(crossProviderTiers=True))
    assert finding_ids(findings) == ["router.ready"]


def test_no_advisory_when_router_disabled() -> None:
    findings = evaluate_router(router_payload(enabled=False))
    assert finding_ids(findings) == ["router.disabled"]


def test_no_advisory_without_active_provider() -> None:
    findings = evaluate_router(router_payload(activeProvider=""))
    assert finding_ids(findings) == ["router.ready"]


def test_legacy_payload_without_new_keys_is_unchanged() -> None:
    legacy = router_payload()
    for key in (
        "activeProvider",
        "crossProviderTiers",
        "tierProviderMismatch",
        "mismatchedTierProviders",
    ):
        legacy.pop(key)
    findings = evaluate_router(legacy)
    assert finding_ids(findings) == ["router.ready"]


def test_router_payload_carries_mismatch_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import opensquilla.gateway.boot as boot
    import opensquilla.gateway.rpc_doctor as rpc_doctor
    from opensquilla.gateway.config import GatewayConfig
    from opensquilla.gateway.rpc import RpcContext

    monkeypatch.setattr(boot, "validate_squilla_router_runtime", lambda config: None)
    monkeypatch.setattr(
        boot, "validate_squilla_router_runtime_deep", lambda config: None
    )

    config = GatewayConfig()
    config.llm.provider = "mainprov"
    config.squilla_router.tiers = {
        "c0": {"model": "dummy-nano-1"},
        "c1": {"model": "dummy-mini-1"},
        "c2": {"model": "dummy-pro-1", "provider": "otherprov"},
        "c3": {"model": "dummy-max-1"},
    }
    ctx = RpcContext(conn_id="test", config=config)

    payload = rpc_doctor._router_payload(ctx, deep=False)
    assert payload["activeProvider"] == "mainprov"
    assert payload["crossProviderTiers"] is False
    assert payload["tierProviderMismatch"] == "route"
    assert payload["mismatchedTierProviders"] == {"c2": "otherprov"}

    findings = evaluate_router(payload)
    assert "router.tier_provider.mismatch" in finding_ids(findings)

    config.squilla_router.tier_provider_mismatch = "veto"
    veto_payload = rpc_doctor._router_payload(ctx, deep=False)
    assert veto_payload["tierProviderMismatch"] == "veto"
    assert "router.tier_provider.mismatch" not in finding_ids(
        evaluate_router(veto_payload)
    )
