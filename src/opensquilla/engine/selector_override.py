"""Single implementation of applying a per-turn model to a cloned selector.

Two turn-path sites apply a model override — the pipeline tail applies the
*routed* model, PromptAssemblerStage applies an *explicit* per-turn model on
top of it. They previously carried textually near-identical blocks that had
already drifted once (the routed_model telemetry realignment existed only in
the stage copy). The mechanics live here exactly once, including the
cross-provider tier path (credential resolution + continuity gate).
"""

from __future__ import annotations

import os
from typing import Any

import structlog

log = structlog.get_logger(__name__)

_ROUTE_SAVINGS_KEYS = (
    "savings_pct",
    "savings_max_price_per_m",
    "savings_routed_price_per_m",
)


def resolve_tier_provider_config(
    config: Any,
    provider_id: str,
    model: str,
    *,
    session_key: str = "",
    turn_metadata: dict[str, Any] | None = None,
) -> Any | None:
    """Build a per-turn ProviderConfig for a cross-provider router tier.

    Credentials come from ``[llm_profiles.<provider_id>]`` when present,
    falling back to the registry env key; the base URL falls back to the
    registry default. Returns None (with a warning) when the provider is
    unknown or a required key cannot be resolved — the caller keeps the
    active provider, never guesses secrets.

    Key resolution order: explicit ``api_key``, then ``api_key_env_pool``
    (session-pinned rotation over env-var names; a pool whose names all
    resolve to nothing degrades to the next step), then ``api_key_env`` or
    the registry env key. A profile without a pool takes exactly the
    pre-pool single-key path. When a pool credential is used, its non-secret
    identifiers are recorded in ``turn_metadata['credential_pool']`` so the
    provider-failure path can park the key on 429/credits/auth failures.
    """
    from opensquilla.provider.registry import UnknownProviderError, get_provider_spec
    from opensquilla.provider.selector import ProviderConfig

    provider_id = (provider_id or "").strip().lower()
    try:
        spec = get_provider_spec(provider_id)
    except UnknownProviderError:
        log.warning("cross_provider_tier.unknown_provider", provider=provider_id)
        return None
    if not spec.runtime_supported:
        log.warning("cross_provider_tier.no_runtime_support", provider=provider_id)
        return None

    profile = (getattr(config, "llm_profiles", None) or {}).get(provider_id)
    api_key = str(getattr(profile, "api_key", "") or "").strip()
    pool_names = [
        str(name).strip()
        for name in (getattr(profile, "api_key_env_pool", None) or [])
        if str(name).strip()
    ]
    if not api_key and pool_names:
        from opensquilla.gateway.llm_runtime import (
            NoCredentialsAvailable,
            profile_credential_pools,
        )

        try:
            pooled = profile_credential_pools().acquire_for_session(
                provider_id,
                pool_names,
                session_key,
            )
        except NoCredentialsAvailable:
            log.warning(
                "cross_provider_tier.credential_pool_exhausted",
                provider=provider_id,
                pool_size=len(pool_names),
            )
            return None
        if pooled is not None:
            api_key = pooled.api_key
            if turn_metadata is not None:
                # Non-secret identifiers only (env-var name + masked key id).
                turn_metadata["credential_pool"] = {
                    "provider": provider_id,
                    "session_key": session_key,
                    "env_name": pooled.env_name,
                    "key_id": pooled.key_id,
                }
    if not api_key:
        env_name = str(getattr(profile, "api_key_env", "") or "").strip() or spec.env_key
        if env_name and env_name != "OAuth":
            api_key = os.environ.get(env_name, "").strip()
    if spec.requires_api_key() and not api_key:
        log.warning(
            "cross_provider_tier.credentials_unresolved",
            provider=provider_id,
            env_key=spec.env_key,
        )
        return None

    base_url = str(getattr(profile, "base_url", "") or "").strip() or spec.default_base_url
    if not base_url and spec.requires_base_url():
        log.warning("cross_provider_tier.base_url_unresolved", provider=provider_id)
        return None

    proxy = str(getattr(profile, "proxy", "") or "").strip() or str(
        getattr(getattr(config, "llm", None), "proxy", "") or ""
    )
    return ProviderConfig(
        provider=provider_id,
        model=model,
        api_key=api_key,
        base_url=base_url,
        proxy=proxy,
        # Provider-bound continuity state (thinking blocks, thought
        # signatures) was minted by another provider; never replay it.
        replay_provider_state=False,
    )


def cross_provider_tier_config(
    config: Any,
    turn_metadata: dict[str, Any],
    model: str,
    *,
    active_provider_id: str,
    session_key: str = "",
) -> Any | None:
    """Return the ProviderConfig for an executable cross-provider tier, or None.

    Execution requires ALL of:
    - ``squilla_router.cross_provider_tiers`` enabled (preview flag, default off)
    - routing applied this turn with a tier provider differing from the active one
    - the provider-state continuity diagnostic did not report unrecoverable
      provider-bound state (``discard_provider_state``) — with only
      provider-bound native state and no portable fallback, switching would
      silently degrade the session
    - resolvable credentials (profile or env), never guessed
    """
    router_cfg = getattr(config, "squilla_router", None)
    if not bool(getattr(router_cfg, "cross_provider_tiers", False)):
        return None
    if turn_metadata.get("routing_applied") is not True:
        return None
    routed_provider = str(turn_metadata.get("routed_provider") or "").strip().lower()
    if not routed_provider or routed_provider == (active_provider_id or "").strip().lower():
        return None
    continuity = turn_metadata.get("provider_state_continuity")
    decision = str(continuity.get("decision") or "") if isinstance(continuity, dict) else ""
    if decision == "discard_provider_state":
        log.warning(
            "cross_provider_tier.blocked_by_continuity",
            provider=routed_provider,
            decision=decision,
        )
        turn_metadata["routed_provider_blocked"] = "provider_state_continuity"
        return None
    return resolve_tier_provider_config(
        config,
        routed_provider,
        model,
        session_key=session_key,
        turn_metadata=turn_metadata,
    )


def apply_model_override(
    selector: Any,
    model: str,
    *,
    turn_metadata: dict[str, Any],
    realign_routed_model: bool,
    tier_provider_config: Any | None = None,
) -> Any:
    """Apply ``model`` to the cloned selector and resolve the provider.

    ``realign_routed_model`` is True only for the explicit-override site: an
    explicit model replaces the routed choice, so ``routed_model`` (read by
    RouterDecisionEvent and comprehensive-savings pricing) must follow and the
    route-savings figures no longer apply. The routed-model site must NOT
    realign — in observe rollout phase the baseline model runs while
    ``routed_model`` intentionally records the would-be routed choice.

    ``tier_provider_config`` switches the turn to a cross-provider tier's
    full ProviderConfig; the router fallback chain is skipped in that case
    (its entries are same-provider models of the provider being left).
    """
    if tier_provider_config is not None and hasattr(selector, "override_provider_config"):
        selector.override_provider_config(tier_provider_config)
        turn_metadata["routed_provider_applied"] = tier_provider_config.provider
        return selector.resolve()

    router_fallback_chain = (
        turn_metadata.get("router_fallback_chain")
        if turn_metadata.get("routing_applied") is True
        else None
    )
    override_with_fallback_chain = getattr(
        selector,
        "override_model_with_fallback_chain",
        None,
    )
    if callable(override_with_fallback_chain) and isinstance(router_fallback_chain, list):
        override_with_fallback_chain(model, router_fallback_chain)
    else:
        selector.override_model(model)
    provider = selector.resolve()

    if realign_routed_model and turn_metadata.get("routed_model") not in (None, model):
        turn_metadata["routed_model"] = model
        for savings_key in _ROUTE_SAVINGS_KEYS:
            if savings_key in turn_metadata:
                turn_metadata[savings_key] = 0.0
    return provider
