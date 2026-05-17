"""Config-backed channel queries for CLI workflows."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from opensquilla.onboarding.config_store import load_config, resolve_config_path
from opensquilla.onboarding.mutations import list_channel_entries


def resolve_channel_config_path(config_path: Path | None) -> tuple[Path, str]:
    """Resolve the gateway config path used by channel commands."""

    return resolve_config_path(config_path)


def load_configured_channel_entries(config_path: Path) -> list[dict[str, Any]]:
    """Load configured channel entries from a gateway config file."""

    return list_channel_entries(load_config(config_path))
