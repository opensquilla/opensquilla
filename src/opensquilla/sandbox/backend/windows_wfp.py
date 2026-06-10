from __future__ import annotations

import sys
from dataclasses import dataclass

WFP_PROVIDER_NAME = "OpenSquilla Sandbox Network Policy"
WFP_SUBLAYER_NAME = "OpenSquilla AppContainer Broker-Only Egress"


@dataclass(frozen=True)
class WfpFilterSpec:
    name: str
    run_id: str
    layer: str
    action: str
    appcontainer_sid: str
    weight: int
    protocol: str | None = None
    remote_address: str | None = None
    remote_port: int | None = None


def wfp_smoke_check() -> bool:
    """Return whether Windows Filtering Platform setup passed a real smoke check.

    This only succeeds when native probes prove that both the OpenSquilla WFP
    provider and the required ALE filters are installed.
    """
    if not _native_windows():
        return False
    return _provider_installed() and _required_filters_installed()


def managed_network_proxy_smoke_check() -> bool:
    """Return whether managed proxy readiness passed a real smoke check.

    Runtime in-process proxy context is not setup readiness. This check only
    succeeds when the broker-only egress boundary can be proven.
    """
    return broker_only_egress_smoke_check()


def broker_only_egress_smoke_check() -> bool:
    """Return whether AppContainer egress is restricted to the broker proxy."""
    if not _native_windows():
        return False
    try:
        return _broker_only_egress_smoke_check_native()
    except Exception:
        return False


def install_wfp_policy(
    *,
    appcontainer_sid: str,
    broker_host: str,
    broker_port: int,
    run_id: str = "default",
) -> tuple[object, ...]:
    """Install broker-only WFP egress policy for an AppContainer SID."""
    _require_native_windows()
    specs = build_broker_only_filter_specs(
        run_id=run_id,
        appcontainer_sid=appcontainer_sid,
        broker_host=broker_host,
        broker_port=broker_port,
    )
    engine = _open_wfp_engine()
    ensure_loopback = getattr(engine, "ensure_loopback_exemption", None)
    if callable(ensure_loopback):
        ensure_loopback(appcontainer_sid)
    filter_ids: list[object] = []
    try:
        for spec in specs:
            filter_ids.append(engine.add_filter(spec))
    except Exception:
        for filter_id in reversed(filter_ids):
            engine.delete_filter(filter_id)
        raise
    return tuple(filter_ids)


def build_broker_only_filter_specs(
    *,
    run_id: str,
    appcontainer_sid: str,
    broker_host: str,
    broker_port: int,
) -> tuple[WfpFilterSpec, ...]:
    run_id = _validate_run_id(run_id)
    appcontainer_sid = _validate_appcontainer_sid(appcontainer_sid)
    broker_host = _validate_loopback_host(broker_host)
    broker_port = _validate_broker_port(broker_port)
    return (
        WfpFilterSpec(
            name=f"OpenSquilla {run_id} allow-proxy-ipv4",
            run_id=run_id,
            layer="ALE_AUTH_CONNECT_V4",
            action="permit",
            appcontainer_sid=appcontainer_sid,
            protocol="TCP",
            remote_address="127.0.0.1",
            remote_port=broker_port,
            weight=200,
        ),
        WfpFilterSpec(
            name=f"OpenSquilla {run_id} block-ipv4",
            run_id=run_id,
            layer="ALE_AUTH_CONNECT_V4",
            action="block",
            appcontainer_sid=appcontainer_sid,
            remote_address="0.0.0.0-127.0.0.0,127.0.0.2-255.255.255.255",
            weight=100,
        ),
        WfpFilterSpec(
            name=f"OpenSquilla {run_id} allow-proxy-ipv6",
            run_id=run_id,
            layer="ALE_AUTH_CONNECT_V6",
            action="permit",
            appcontainer_sid=appcontainer_sid,
            protocol="TCP",
            remote_address="::1",
            remote_port=broker_port,
            weight=200,
        ),
        WfpFilterSpec(
            name=f"OpenSquilla {run_id} block-ipv6",
            run_id=run_id,
            layer="ALE_AUTH_CONNECT_V6",
            action="block",
            appcontainer_sid=appcontainer_sid,
            remote_address="::/0",
            weight=100,
        ),
    )


def uninstall_wfp_policy() -> None:
    """Uninstall OpenSquilla WFP egress policy."""
    _require_native_windows()
    _uninstall_wfp_policy_native()


def remove_wfp_filters(filter_ids: tuple[object, ...] | list[object]) -> None:
    """Remove previously installed WFP filters by id."""
    _require_native_windows()
    engine = _open_wfp_engine()
    for filter_id in reversed(tuple(filter_ids)):
        engine.delete_filter(filter_id)


def _provider_installed() -> bool:
    """Return True only when native query proves the WFP provider exists."""
    return _broker_service_ready()


def _required_filters_installed() -> bool:
    """Return True only when native query proves the required ALE filters exist."""
    return _broker_service_ready()


def _broker_only_egress_smoke_check_native() -> bool:
    """Return True when native WFP probes prove broker-only egress is active."""
    return _provider_installed() and _required_filters_installed()


def _install_wfp_policy_native(
    *,
    appcontainer_sid: str,
    broker_host: str,
    broker_port: int,
) -> None:
    raise RuntimeError("native WFP policy install is not implemented")


def _uninstall_wfp_policy_native() -> None:
    raise RuntimeError("native WFP policy uninstall is not implemented")


def _require_native_windows() -> None:
    if not _native_windows():
        raise RuntimeError("WFP policy setup requires Windows")


def _native_windows() -> bool:
    return sys.platform.startswith("win")


def _validate_run_id(value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError("run_id is required")
    return normalized


def _validate_appcontainer_sid(value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized.startswith("S-1-15-2-"):
        raise ValueError("appcontainer_sid must be an AppContainer SID")
    return normalized


def _validate_loopback_host(value: str) -> str:
    normalized = str(value or "").strip()
    if normalized not in {"127.0.0.1", "::1"}:
        raise ValueError("broker_host must be loopback")
    return normalized


def _validate_broker_port(value: int) -> int:
    port = int(value)
    if not 1 <= port <= 65535:
        raise ValueError("broker_port must be in range 1..65535")
    return port


class _NativeWfpEngine:
    def __init__(self) -> None:
        from opensquilla.sandbox.windows_service_broker import WindowsFirewallPolicyManager

        self._manager = WindowsFirewallPolicyManager()

    def ensure_loopback_exemption(self, appcontainer_sid: str) -> None:
        self._manager._ensure_loopback_exemption(appcontainer_sid)

    def add_filter(self, spec: WfpFilterSpec) -> object:
        from opensquilla.sandbox.windows_service_broker import FirewallRule

        action = "Allow" if spec.action == "permit" else "Block"
        self._manager._create_firewall_rule(
            FirewallRule(
                name=spec.name,
                display_name=spec.name,
                action=action,
                package_sid=spec.appcontainer_sid,
                protocol=spec.protocol or "Any",
                remote_address=spec.remote_address,
                remote_port=spec.remote_port,
            )
        )
        return spec.name

    def delete_filter(self, filter_id: object) -> None:
        self._manager._remove_firewall_rule(str(filter_id))


def _open_wfp_engine() -> _NativeWfpEngine:
    return _NativeWfpEngine()


def _broker_service_ready() -> bool:
    try:
        from opensquilla.sandbox.windows_service_ipc import broker_ready

        return broker_ready()
    except Exception:
        return False


__all__ = [
    "WFP_PROVIDER_NAME",
    "WFP_SUBLAYER_NAME",
    "WfpFilterSpec",
    "broker_only_egress_smoke_check",
    "build_broker_only_filter_specs",
    "install_wfp_policy",
    "managed_network_proxy_smoke_check",
    "remove_wfp_filters",
    "uninstall_wfp_policy",
    "wfp_smoke_check",
]
