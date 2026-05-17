"""Config-backed provider mutations for CLI workflows."""

from __future__ import annotations

from pathlib import Path

from opensquilla.onboarding.config_store import (
    PersistResult,
    default_config_path,
    load_config,
    persist_config,
)
from opensquilla.onboarding.mutations import upsert_llm_provider


def configure_provider_in_config(
    provider: str,
    *,
    model: str,
    api_key: str,
    base_url: str,
    proxy: str,
    config_path: Path | None,
) -> PersistResult:
    """Apply provider settings to the configured gateway config file."""

    target = config_path or default_config_path()
    cfg = load_config(target)
    result = upsert_llm_provider(
        cfg,
        provider_id=provider,
        model=model,
        api_key=api_key,
        base_url=base_url,
        proxy=proxy,
    )
    return persist_config(
        result.config,
        path=target,
        restart_required=result.restart_required,
    )
