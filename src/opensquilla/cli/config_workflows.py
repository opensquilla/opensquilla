"""CLI workflows for config commands."""

from __future__ import annotations

from pathlib import Path

from opensquilla.cli.config_presenters import (
    emit_config_export_hint,
    emit_config_table,
    emit_config_value,
    emit_missing_config_key,
)
from opensquilla.cli.config_queries import (
    is_missing_config_value,
    load_public_config,
    lookup_config_value,
)


def get_config_for_cli(
    key: str,
    *,
    config_path: Path | None,
) -> None:
    """Load and emit public config data for the CLI."""

    public_config = load_public_config(config_path)
    if not key:
        emit_config_table(public_config.data)
        return

    value = lookup_config_value(public_config.data, key)
    if is_missing_config_value(value):
        emit_missing_config_key(key)
    emit_config_value(key, value)


def set_config_for_cli(key: str, value: str) -> None:
    """Emit the env-var backed config set hint for the CLI."""

    emit_config_export_hint(key, value)
