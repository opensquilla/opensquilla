"""Config-backed search provider mutations for CLI workflows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from opensquilla.gateway.config import GatewayConfig
from opensquilla.onboarding.config_store import (
    PersistResult,
    default_config_path,
    load_config,
    persist_config,
)
from opensquilla.onboarding.mutations import upsert_search_provider


@dataclass(frozen=True)
class SearchConfigureResult:
    """Persist metadata plus the mutated config used for follow-up warnings."""

    persist: PersistResult
    config: GatewayConfig


def configure_search_provider_in_config(
    provider: str,
    *,
    api_key: str,
    api_key_env: str,
    max_results: int,
    proxy: str,
    use_env_proxy: bool,
    fallback_policy: str,
    diagnostics: bool,
    config_path: Path | None,
) -> SearchConfigureResult:
    """Apply search provider settings to the configured gateway config file."""

    target = config_path or default_config_path()
    cfg = load_config(target)
    mutation = upsert_search_provider(
        cfg,
        provider_id=provider,
        api_key=api_key,
        api_key_env=api_key_env,
        max_results=max_results,
        proxy=proxy,
        use_env_proxy=use_env_proxy,
        fallback_policy=fallback_policy,
        diagnostics=diagnostics,
    )
    persist = persist_config(
        mutation.config,
        path=target,
        restart_required=mutation.restart_required,
    )
    return SearchConfigureResult(persist=persist, config=mutation.config)
