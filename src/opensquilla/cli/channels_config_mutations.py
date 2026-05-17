"""Config-backed channel mutations for CLI workflows."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from opensquilla.cli.channel_fields import (
    apply_channel_token,
    parse_channel_field_pairs,
)
from opensquilla.onboarding.config_store import PersistResult, load_config, persist_config
from opensquilla.onboarding.mutations import upsert_channel


def add_channel_to_config(
    type_name: str,
    *,
    name: str,
    token: str,
    enabled: bool,
    agent_id: str,
    fields: list[str],
    config_path: Path,
) -> PersistResult:
    """Add or update a channel entry in a gateway config file."""

    payload: dict[str, Any] = {
        "type": type_name,
        "name": name,
        "enabled": enabled,
        "agent_id": agent_id,
    }
    apply_channel_token(payload, type_name, token)
    payload.update(parse_channel_field_pairs(fields, type_name))

    cfg = load_config(config_path)
    result = upsert_channel(cfg, entry_payload=payload)
    return persist_config(result.config, path=config_path, restart_required=True)


def edit_channel_in_config(
    name: str,
    *,
    token: str,
    enabled: bool | None,
    agent_id: str,
    fields: list[str],
    config_path: Path,
) -> tuple[PersistResult, str]:
    """Patch an existing channel entry in a gateway config file."""

    cfg = load_config(config_path)
    existing = next(
        (
            entry.model_dump(mode="python")
            for entry in cfg.channels.channels
            if entry.name == name
        ),
        None,
    )
    if existing is None:
        raise ValueError(f"no channel named {name!r}")

    type_name = existing["type"]
    overrides: dict[str, Any] = {"type": type_name, "name": name}
    if enabled is not None:
        overrides["enabled"] = enabled
    if agent_id:
        overrides["agent_id"] = agent_id
    apply_channel_token(overrides, type_name, token)
    overrides.update(parse_channel_field_pairs(fields, type_name))

    payload = {**existing, **overrides}
    result = upsert_channel(cfg, entry_payload=payload)
    persist = persist_config(result.config, path=config_path, restart_required=True)
    return persist, str(type_name)
