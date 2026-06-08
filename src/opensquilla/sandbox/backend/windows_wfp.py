from __future__ import annotations

import sys

WFP_PROVIDER_NAME = "OpenSquilla Sandbox Network Policy"
WFP_SUBLAYER_NAME = "OpenSquilla AppContainer Broker-Only Egress"


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

    Runtime in-process proxy context is not setup readiness. Later managed
    network tasks will replace this conservative placeholder with checks that
    prove the proxy boundary needed by Windows backends is available.
    """
    return False


def install_wfp_policy(
    *,
    appcontainer_sid: str,
    broker_host: str,
    broker_port: int,
) -> None:
    """Install broker-only WFP egress policy for an AppContainer SID."""
    _require_native_windows()
    if not appcontainer_sid.startswith("S-1-15-2-"):
        raise ValueError("appcontainer_sid must be an AppContainer SID")
    if not broker_host:
        raise ValueError("broker_host must be non-empty")
    if not 1 <= broker_port <= 65535:
        raise ValueError("broker_port must be in range 1..65535")

    _install_wfp_policy_native(
        appcontainer_sid=appcontainer_sid,
        broker_host=broker_host,
        broker_port=broker_port,
    )


def uninstall_wfp_policy() -> None:
    """Uninstall OpenSquilla WFP egress policy."""
    _require_native_windows()
    _uninstall_wfp_policy_native()


def _provider_installed() -> bool:
    """Return True only when native query proves the WFP provider exists."""
    return False


def _required_filters_installed() -> bool:
    """Return True only when native query proves the required ALE filters exist."""
    return False


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


__all__ = [
    "WFP_PROVIDER_NAME",
    "WFP_SUBLAYER_NAME",
    "install_wfp_policy",
    "managed_network_proxy_smoke_check",
    "uninstall_wfp_policy",
    "wfp_smoke_check",
]
