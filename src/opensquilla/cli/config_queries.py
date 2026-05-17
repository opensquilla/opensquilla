"""Config-backed queries for CLI config workflows."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from opensquilla.gateway.config import GatewayConfig


@dataclass(frozen=True)
class PublicConfig:
    """Public gateway config data loaded for CLI display."""

    data: dict[str, Any]


_MISSING = object()


def load_public_config(config_path: Path | None) -> PublicConfig:
    """Load gateway config using CLI path/env precedence and return redacted data."""

    cfg = GatewayConfig.load(
        config_path or os.environ.get("OPENSQUILLA_GATEWAY_CONFIG_PATH")
    )
    return PublicConfig(data=cfg.to_public_dict())


def lookup_config_value(data: dict[str, Any], key: str) -> Any:
    """Look up a dot-notation config key in public config data."""

    val: Any = data
    for part in key.split("."):
        if isinstance(val, dict) and part in val:
            val = val[part]
        else:
            return _MISSING
    return val


def is_missing_config_value(value: Any) -> bool:
    """Return whether a lookup result represents a missing config key."""

    return value is _MISSING
