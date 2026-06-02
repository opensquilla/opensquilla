"""Shared sandbox posture status payloads."""

from __future__ import annotations

from typing import Any

from opensquilla.sandbox.package_bundles import PACKAGE_BUNDLES
from opensquilla.sandbox.run_mode import config_run_mode, display_name, execution_target


def posture(config: Any) -> str:
    return config_run_mode(config).value


def status_payload(config: Any, *, restart_required: bool = False) -> dict[str, Any]:
    run_mode = config_run_mode(config)
    sandbox_cfg = config.sandbox
    network_default = str(getattr(sandbox_cfg, "network_default", "none"))
    managed_network = (
        "ready"
        if bool(sandbox_cfg.sandbox) and network_default == "proxy_allowlist"
        else "blocked"
    )
    return {
        "run_mode": run_mode.value,
        "run_mode_label": display_name(run_mode),
        "execution_target": execution_target(run_mode),
        "posture": run_mode.value,
        "backend": str(getattr(sandbox_cfg, "backend", "auto")),
        "managed_network": managed_network,
        "sandbox": {
            "sandbox": bool(sandbox_cfg.sandbox),
            "security_grading": bool(sandbox_cfg.security_grading),
            "network_default": network_default,
        },
        "bundle_catalog": [
            {"bundle_id": bundle_id, "domains": list(domains)}
            for bundle_id, domains in PACKAGE_BUNDLES.items()
        ],
        "permissions": {
            "default_mode": str(config.permissions.default_mode),
        },
        "restart_required": restart_required,
    }
