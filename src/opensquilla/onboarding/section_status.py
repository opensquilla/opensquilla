"""Declarative per-section verifiers for onboarding readiness.

Each verifier is a pure function ``(cfg) -> SectionStatus`` that reflects the
current state of one onboarding section as derived from the gateway config.
Verifiers never raise — internal lookup failures map to ``UNKNOWN`` so
``get_onboarding_status`` and ``--if-needed`` stay total functions over
arbitrary configs.

This module is the single source of truth consulted by:

* ``onboard --if-needed`` to decide whether onboarding can be skipped
* ``opensquilla onboard status`` to render an at-a-glance readiness table
* ``OnboardingStatus`` (status.py) to recompute the legacy boolean fields
  while keeping the existing WebUI / RPC contract intact

Adding a new section means writing one verifier here and registering it in
``section_verifiers()``; no other call site needs to change.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from enum import StrEnum
from typing import Any, cast

from opensquilla.gateway.config import GatewayConfig
from opensquilla.onboarding.image_generation_specs import (
    get_image_generation_provider_setup_spec,
    list_image_generation_provider_setup_specs,
)
from opensquilla.onboarding.provider_specs import get_provider_setup_spec
from opensquilla.onboarding.search_specs import get_search_provider_setup_spec


class SectionStatus(StrEnum):
    """Readiness state of one onboarding section.

    The naming is user-facing: ``MISSING`` for unfinished setup,
    ``DEGRADED`` for "user told us to use an env var that isn't set right now",
    ``OPTIONAL`` for sections the user intentionally opted out of,
    ``UNKNOWN`` for verifier-side lookup failures. ``StrEnum`` keeps the values
    JSON-serialisable for the ``onboard status --json`` output.
    """

    OK = "ok"
    MISSING = "missing"
    DEGRADED = "degraded"
    OPTIONAL = "optional"
    UNKNOWN = "unknown"


def _str(cfg: object, name: str) -> str:
    return (getattr(cfg, name, "") or "").strip()


def llm_section_status(cfg: GatewayConfig) -> SectionStatus:
    """LLM is the only section that never legitimately resolves to OPTIONAL.

    The runtime cannot operate without a usable language-model provider, so a
    missing or undecidable LLM always blocks onboarding.
    """
    llm = cfg.llm
    if not _str(llm, "provider") or not _str(llm, "model"):
        return SectionStatus.MISSING
    try:
        spec = get_provider_setup_spec(llm.provider)
    except KeyError:
        return SectionStatus.UNKNOWN
    if not spec.runtime_supported:
        return SectionStatus.UNKNOWN
    if spec.requires_base_url and not _str(llm, "base_url"):
        return SectionStatus.MISSING
    if not spec.requires_api_key:
        return SectionStatus.OK
    if llm.api_key and "llm.api_key" not in getattr(cfg, "_runtime_secret_paths", set()):
        return SectionStatus.OK
    env_key = _str(llm, "api_key_env")
    if env_key:
        return SectionStatus.OK if os.environ.get(env_key) else SectionStatus.DEGRADED
    return SectionStatus.MISSING


def router_section_status(cfg: GatewayConfig) -> SectionStatus:
    """``enabled=False`` is a deliberate operator choice, not a problem.

    ``SquillaRouterConfig`` does not carry a ``mode`` field — ``upsert_router``
    flips ``enabled`` and ``tier_profile`` according to the onboard option.
    A disabled router is the canonical "I do not want local routing" state.
    """
    router = getattr(cfg, "squilla_router", None)
    if router is None:
        return SectionStatus.OPTIONAL
    return SectionStatus.OK if bool(getattr(router, "enabled", False)) else SectionStatus.OPTIONAL


def search_section_status(cfg: GatewayConfig) -> SectionStatus:
    provider = _str(cfg, "search_provider")
    if not provider:
        return SectionStatus.OPTIONAL
    try:
        spec = get_search_provider_setup_spec(provider)
    except KeyError:
        return SectionStatus.UNKNOWN
    if not spec.requires_api_key:
        return SectionStatus.OK
    if getattr(cfg, "search_api_key", ""):
        return SectionStatus.OK
    env_key = _str(cfg, "search_api_key_env")
    if env_key:
        return SectionStatus.OK if os.environ.get(env_key) else SectionStatus.DEGRADED
    return SectionStatus.MISSING


def channels_section_status(cfg: GatewayConfig) -> SectionStatus:
    """Empty or all-disabled channel list reads as an opt-out, not a failure."""
    channels = list(getattr(cfg.channels, "channels", []) or [])
    if any(getattr(c, "enabled", False) for c in channels):
        return SectionStatus.OK
    return SectionStatus.OPTIONAL


def image_generation_section_status(cfg: GatewayConfig) -> SectionStatus:
    image_cfg = getattr(cfg, "image_generation", None)
    if image_cfg is None or not bool(getattr(image_cfg, "enabled", False)):
        return SectionStatus.OPTIONAL
    aggregate = SectionStatus.MISSING
    for provider_id in _configured_image_generation_provider_ids(cfg):
        credential = _image_generation_credential_state(cfg, provider_id)
        if credential is SectionStatus.OK:
            return SectionStatus.OK
        # ``UNKNOWN`` from a bad provider reference should win over a plain
        # ``MISSING`` from a credential-less but valid provider so the
        # operator sees the config-shape problem first; ``DEGRADED`` still
        # beats ``MISSING`` for the same reason as LLM/search.
        if credential is SectionStatus.UNKNOWN:
            aggregate = SectionStatus.UNKNOWN
        elif credential is SectionStatus.DEGRADED and aggregate is not SectionStatus.UNKNOWN:
            aggregate = SectionStatus.DEGRADED
    return aggregate


def _image_generation_credential_state(
    cfg: GatewayConfig,
    provider_id: str,
) -> SectionStatus:
    """Mirror ``llm`` / ``search`` credential semantics for image generation.

    Returns one of ``OK / MISSING / DEGRADED / UNKNOWN`` so the section-level
    reducer can preserve the contract of the broader ``SectionStatus`` enum.

    Resolution order (each branch wins if it produces ``OK``):
      1. explicit ``provider_cfg.api_key`` (paste) -> ``OK``
      2. operator-explicit env_key resolved in ``os.environ`` -> ``OK``
      3. spec default env_key resolved in ``os.environ`` -> ``OK``
      4. matching LLM provider with an explicit ``api_key`` (image-gen reuses it) -> ``OK``
      5. operator-explicit env_key declared but absent -> ``DEGRADED``
      6. otherwise -> ``MISSING``

    Known tradeoff: the config schema does not record whether the operator
    explicitly picked the *default* env var name (e.g. ``OPENAI_API_KEY``)
    or whether the value arrived from a Pydantic field default. The
    ``cfg_env_key == spec_env_key`` test below treats matching values as
    spec-default so a fresh ``GatewayConfig()`` does not flap to
    ``DEGRADED`` whenever the spec env var happens to be unset. The cost:
    an operator who deliberately picked the spec-default env var and later
    loses that variable from the environment will see ``MISSING`` rather
    than ``DEGRADED``. Recording an explicit credential source on the
    provider config would close this gap and is left for a config schema
    change.
    """
    try:
        spec = get_image_generation_provider_setup_spec(provider_id)
    except KeyError:
        return SectionStatus.UNKNOWN

    providers = getattr(getattr(cfg, "image_generation", None), "providers", None)
    provider_cfg = getattr(providers, provider_id, None) if providers is not None else None

    provider_cfg_any = cast(Any, provider_cfg)
    if provider_cfg_any is not None and provider_cfg_any.api_key:
        return SectionStatus.OK

    # An ``api_key_env`` value that matches the spec default arrives from
    # field defaults rather than an operator decision, so it should not
    # short-circuit to ``DEGRADED``. Only treat the reference as explicit
    # when the operator overrode the spec default.
    spec_env_key = (getattr(spec, "env_key", "") or "").strip()
    cfg_env_key = ""
    if provider_cfg is not None:
        cfg_env_key = (getattr(provider_cfg, "api_key_env", "") or "").strip()
    explicit_env_key = cfg_env_key if cfg_env_key and cfg_env_key != spec_env_key else ""

    if explicit_env_key and os.environ.get(explicit_env_key):
        return SectionStatus.OK
    if spec_env_key and os.environ.get(spec_env_key):
        return SectionStatus.OK

    llm = getattr(cfg, "llm", None)
    if (
        getattr(llm, "provider", "").strip().lower() == provider_id
        and getattr(llm, "api_key", "")
    ):
        return SectionStatus.OK

    # Nothing produced an OK; classify how the operator left the provider.
    if explicit_env_key:
        return SectionStatus.DEGRADED
    return SectionStatus.MISSING


def section_verifiers() -> dict[str, Callable[[GatewayConfig], SectionStatus]]:
    """Registry consumed by ``get_onboarding_status`` and ``onboard status``."""
    return {
        "llm": llm_section_status,
        "router": router_section_status,
        "search": search_section_status,
        "channels": channels_section_status,
        "image_generation": image_generation_section_status,
    }


def needs_onboarding(sections: dict[str, SectionStatus]) -> bool:
    """Any non-OK, non-OPTIONAL section means onboarding has unfinished work.

    DEGRADED is included so a missing env var surfaces on the next
    ``--if-needed`` run rather than being silently treated as resolved.
    """
    return any(
        status not in (SectionStatus.OK, SectionStatus.OPTIONAL)
        for status in sections.values()
    )


def _configured_image_generation_provider_ids(cfg: GatewayConfig) -> list[str]:
    image_cfg = cfg.image_generation
    primary = getattr(image_cfg, "primary", "")
    fallbacks = list(getattr(image_cfg, "fallbacks", []) or [])
    default_primary = "openai/gpt-image-1"
    explicit_routing = bool(fallbacks) or bool(primary and primary != default_primary)
    refs = (
        [primary, *fallbacks]
        if explicit_routing
        else [
            spec.default_model
            for spec in list_image_generation_provider_setup_specs()
            if spec.runtime_supported
        ]
    )
    seen: set[str] = set()
    result: list[str] = []
    for ref in refs:
        provider_id, sep, _model = ref.partition("/")
        provider_id = provider_id.strip()
        if sep and provider_id and provider_id not in seen:
            seen.add(provider_id)
            result.append(provider_id)
    return result
