"""Derive a structured OnboardingStatus from a GatewayConfig.

The per-section truth lives in :mod:`opensquilla.onboarding.section_status`;
this module composes those verifiers, computes the legacy boolean view
required by WebUI RPC and ``next_steps``, and exposes ``llm_source`` /
``image_generation_*`` annotations that the CLI status renderers need.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from opensquilla.gateway.config import GatewayConfig
from opensquilla.onboarding.config_store import default_config_path
from opensquilla.onboarding.image_generation_specs import (
    get_image_generation_provider_setup_spec,
    list_image_generation_provider_setup_specs,
)
from opensquilla.onboarding.provider_specs import get_provider_setup_spec
from opensquilla.onboarding.search_specs import get_search_provider_setup_spec
from opensquilla.onboarding.section_status import (
    FIRST_RUN_REQUIRED_SECTIONS,
    SectionStatus,
    channels_section_status,
    image_generation_section_status,
    llm_section_status,
    memory_embedding_section_status,
    router_section_status,
    search_section_status,
    section_verifiers,
)
from opensquilla.onboarding.section_status import (
    needs_onboarding as _needs_onboarding,
)


@dataclass(frozen=True)
class OnboardingStatus:
    config_path: str | None
    has_config: bool
    llm_configured: bool
    llm_source: str
    llm_env_key: str
    search_configured: bool
    search_provider: str
    search_source: str
    search_env_key: str
    image_generation_configured: bool
    image_generation_enabled: bool
    image_generation_source: str
    image_generation_provider: str
    image_generation_primary: str
    image_generation_env_key: str
    memory_embedding_configured: bool
    memory_embedding_provider: str
    memory_embedding_source: str
    memory_embedding_env_key: str
    channel_count: int
    channels_configured: bool
    needs_onboarding: bool
    sections: dict[str, SectionStatus] = field(default_factory=dict)
    section_details: dict[str, dict[str, object]] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()


_SECTION_LABELS: dict[str, str] = {
    "llm": "Provider",
    "router": "Router",
    "search": "Web search",
    "channels": "Channels",
    "image_generation": "Image generation",
    "memory_embedding": "Memory embedding",
}


def _section_details(
    sections: dict[str, SectionStatus],
    detail_text: dict[str, str] | None = None,
    runtime_blocking: set[str] | None = None,
) -> dict[str, dict[str, object]]:
    details: dict[str, dict[str, object]] = {}
    for name, state in sections.items():
        required = name in FIRST_RUN_REQUIRED_SECTIONS
        action_required = state not in (SectionStatus.OK, SectionStatus.OPTIONAL)
        blocking = (required and action_required) or (
            action_required and name in (runtime_blocking or set())
        )
        details[name] = {
            "label": _SECTION_LABELS.get(name, name.replace("_", " ").title()),
            "status": state.value,
            "required": required,
            "optional": not required,
            "blocking": blocking,
            "actionRequired": action_required,
        }
        if detail_text and detail_text.get(name):
            details[name]["detail"] = detail_text[name]
    return details


def _source_detail(source: str, env_key: str = "") -> str:
    if source == "explicit":
        return "stored key"
    if source == "env":
        return f"env key visible: {env_key}" if env_key else "env key visible"
    if source == "missing_env":
        return f"env key not visible: {env_key}" if env_key else "env key not visible"
    if source == "not_required":
        return "no key required"
    return ""


def _with_provider(provider: str, detail: str) -> str:
    if provider and detail:
        return f"{provider} ({detail})"
    return provider or detail


def _router_detail(cfg: GatewayConfig, llm_source: str) -> str:
    router = getattr(cfg, "squilla_router", None)
    if router is None or not bool(getattr(router, "enabled", False)):
        return "disabled"
    llm = getattr(cfg, "llm", None)
    if llm_source == "none" or not getattr(llm, "provider", ""):
        return "uses SquillaRouter after provider setup"
    profile = str(getattr(router, "tier_profile", "") or "").strip()
    if profile:
        return f"SquillaRouter profile: {profile}"
    default_tier = str(getattr(router, "default_tier", "") or "t1").strip()
    return f"SquillaRouter default tier: {default_tier}"


def _llm_source(cfg: GatewayConfig, status: SectionStatus) -> tuple[str, str]:
    """Re-derive the legacy ``llm_source`` annotation alongside the verifier.

    The verifier collapses the source detail into a single enum so it stays
    composable with the other sections; this helper keeps the existing
    ``"explicit" / "env" / "missing_env" / "none"`` annotation alive for the
    CLI/WebUI renderers that already display it.
    """
    llm = cfg.llm
    if not llm.provider or not llm.model:
        return "none", ""
    try:
        spec = get_provider_setup_spec(llm.provider)
    except KeyError:
        return "none", ""
    if not spec.runtime_supported or not spec.requires_api_key:
        return "not_required", ""
    if status is SectionStatus.OK and llm.api_key and (
        "llm.api_key" not in getattr(cfg, "_runtime_secret_paths", set())
    ):
        return "explicit", ""
    env_key = (getattr(llm, "api_key_env", "") or "").strip()
    if env_key and os.environ.get(env_key):
        return "env", env_key
    if env_key:
        return "missing_env", env_key
    return "none", ""


def _search_annotations(
    cfg: GatewayConfig,
    status: SectionStatus,
) -> tuple[str, str, str]:
    provider = str(getattr(cfg, "search_provider", "") or "").strip()
    if not provider:
        return "", "none", ""
    try:
        spec = get_search_provider_setup_spec(provider)
    except KeyError:
        return provider, "none", ""
    if not spec.requires_api_key:
        return provider, "not_required", ""
    if getattr(cfg, "search_api_key", ""):
        return provider, "explicit", ""
    env_key = str(getattr(cfg, "search_api_key_env", "") or "").strip()
    if env_key and os.environ.get(env_key):
        return provider, "env", env_key
    if env_key:
        return provider, "missing_env", env_key
    if status is SectionStatus.OK:
        return provider, "env", spec.env_key
    return provider, "none", spec.env_key


def _image_generation_provider_config(cfg: GatewayConfig, provider_id: str) -> object | None:
    providers = getattr(getattr(cfg, "image_generation", None), "providers", None)
    return getattr(providers, provider_id, None) if providers is not None else None


def _image_generation_provider_source(
    cfg: GatewayConfig,
    provider_id: str,
) -> tuple[str, str]:
    try:
        spec = get_image_generation_provider_setup_spec(provider_id)
    except KeyError:
        return "", ""

    provider_cfg = _image_generation_provider_config(cfg, provider_id)
    explicit_key = getattr(provider_cfg, "api_key", "") if provider_cfg else ""
    if explicit_key:
        return "explicit", spec.env_key

    spec_env_key = (getattr(spec, "env_key", "") or "").strip()
    cfg_env_key = (
        (getattr(provider_cfg, "api_key_env", "") or "").strip()
        if provider_cfg
        else ""
    )
    explicit_env_key = cfg_env_key if cfg_env_key and cfg_env_key != spec_env_key else ""
    if explicit_env_key:
        return (
            ("env", explicit_env_key)
            if os.environ.get(explicit_env_key)
            else ("missing_env", explicit_env_key)
        )
    if spec_env_key and os.environ.get(spec_env_key):
        return "env", spec_env_key

    llm = getattr(cfg, "llm", None)
    if getattr(llm, "provider", "").strip().lower() == provider_id and getattr(llm, "api_key", ""):
        return "llm_fallback", spec.env_key
    return "", spec_env_key


def _image_generation_provider_has_operator_credential(
    cfg: GatewayConfig,
    provider_id: str,
    spec: object,
) -> bool:
    provider_cfg = _image_generation_provider_config(cfg, provider_id)
    if provider_cfg is None:
        return False
    if getattr(provider_cfg, "api_key", ""):
        return True
    spec_env_key = (getattr(spec, "env_key", "") or "").strip()
    cfg_env_key = (getattr(provider_cfg, "api_key_env", "") or "").strip()
    return bool(cfg_env_key and cfg_env_key != spec_env_key)


def _configured_image_generation_provider_ids(cfg: GatewayConfig) -> list[str]:
    image_cfg = cfg.image_generation
    refs: list[str] = []
    primary = getattr(image_cfg, "primary", "")
    fallbacks = list(getattr(image_cfg, "fallbacks", []) or [])
    default_primary = "openai/gpt-image-1"
    explicit_model_routing = bool(fallbacks) or bool(primary and primary != default_primary)
    specs = [
        spec
        for spec in list_image_generation_provider_setup_specs()
        if spec.runtime_supported
    ]
    explicit_provider_ids = [
        spec.provider_id
        for spec in specs
        if _image_generation_provider_has_operator_credential(
            cfg,
            spec.provider_id,
            spec,
        )
    ]
    if not explicit_model_routing and explicit_provider_ids:
        return explicit_provider_ids
    if explicit_model_routing:
        refs = [primary, *fallbacks]
    else:
        refs = [spec.default_model for spec in specs]

    provider_ids: list[str] = []
    seen: set[str] = set()
    for ref in refs:
        provider_id, sep, _model = ref.partition("/")
        provider_id = provider_id.strip()
        if sep and provider_id and provider_id not in seen:
            seen.add(provider_id)
            provider_ids.append(provider_id)
    return provider_ids


def _image_generation_annotations(
    cfg: GatewayConfig,
    status: SectionStatus,
) -> tuple[str, str, str, str]:
    image_cfg = cfg.image_generation
    primary = getattr(image_cfg, "primary", "")
    if status is SectionStatus.OPTIONAL:
        return "none", "", primary, ""
    for provider_id in _configured_image_generation_provider_ids(cfg):
        source, env_key = _image_generation_provider_source(cfg, provider_id)
        if source:
            return source, provider_id, primary, env_key
    return "none", "", primary, ""


def _memory_embedding_annotations(
    cfg: GatewayConfig,
    status: SectionStatus,
) -> tuple[str, str]:
    memory = getattr(cfg, "memory", None)
    embedding = getattr(memory, "embedding", None)
    if embedding is None:
        return "none", ""
    provider = str(getattr(embedding, "requested_provider", "") or "auto")
    if provider in {"none", "auto", "local", "ollama"}:
        return "not_required", ""
    remote = getattr(embedding, "remote", None)
    key = (
        str(getattr(remote, "api_key", "") or "")
        or str(getattr(embedding, "api_key", "") or "")
    )
    if key:
        return "explicit", ""
    env_key = str(getattr(remote, "api_key_env", "") or "").strip()
    if env_key and os.environ.get(env_key):
        return "env", env_key
    if env_key:
        return "missing_env", env_key
    if status is SectionStatus.OK:
        return "env", env_key
    return "none", env_key


def _runtime_blocking_sections(
    *,
    memory_provider: str,
    memory_status: SectionStatus,
) -> set[str]:
    blocking: set[str] = set()
    if (
        memory_provider in {"openai", "openai-compatible"}
        and memory_status not in (SectionStatus.OK, SectionStatus.OPTIONAL)
    ):
        blocking.add("memory_embedding")
    return blocking


def get_onboarding_status(config: GatewayConfig) -> OnboardingStatus:
    path = Path(config.config_path).expanduser() if config.config_path else default_config_path()
    has_config = path.exists()

    sections = {name: verifier(config) for name, verifier in section_verifiers().items()}

    llm_status = sections["llm"]
    search_status = sections["search"]
    image_status = sections["image_generation"]
    memory_status = sections["memory_embedding"]
    llm_source, llm_env_key = _llm_source(config, llm_status)
    search_provider, search_source, search_env_key = _search_annotations(
        config, search_status
    )
    image_source, image_provider, image_primary, image_env_key = _image_generation_annotations(
        config, image_status
    )
    memory_embedding = getattr(getattr(config, "memory", None), "embedding", None)
    memory_provider = str(
        getattr(memory_embedding, "requested_provider", "")
        or getattr(memory_embedding, "provider", "")
        or ""
    )
    memory_source, memory_env_key = _memory_embedding_annotations(config, memory_status)
    runtime_blocking = _runtime_blocking_sections(
        memory_provider=memory_provider,
        memory_status=memory_status,
    )
    detail_text = {
        "llm": _source_detail(llm_source, llm_env_key),
        "router": _router_detail(config, llm_source),
        "search": _source_detail(search_source, search_env_key),
        "image_generation": _with_provider(
            image_provider,
            (
                "same provider key"
                if image_source == "llm_fallback"
                else _source_detail(image_source, image_env_key)
            ),
        ),
        "memory_embedding": _with_provider(
            memory_provider,
            _source_detail(memory_source, memory_env_key),
        ),
    }

    enabled_channels = [c for c in config.channels.channels if c.enabled]

    return OnboardingStatus(
        config_path=str(path),
        has_config=has_config,
        llm_configured=llm_status is SectionStatus.OK,
        llm_source=llm_source,
        llm_env_key=llm_env_key,
        search_configured=search_status is SectionStatus.OK,
        search_provider=search_provider,
        search_source=search_source,
        search_env_key=search_env_key,
        image_generation_configured=image_status is SectionStatus.OK,
        image_generation_enabled=bool(getattr(config.image_generation, "enabled", False)),
        image_generation_source=image_source,
        image_generation_provider=image_provider,
        image_generation_primary=image_primary,
        image_generation_env_key=image_env_key,
        memory_embedding_configured=memory_status is SectionStatus.OK,
        memory_embedding_provider=memory_provider,
        memory_embedding_source=memory_source,
        memory_embedding_env_key=memory_env_key,
        channel_count=len(config.channels.channels),
        channels_configured=bool(enabled_channels),
        needs_onboarding=_needs_onboarding(sections) or bool(runtime_blocking),
        sections=sections,
        section_details=_section_details(sections, detail_text, runtime_blocking),
    )


__all__ = [
    "OnboardingStatus",
    "SectionStatus",
    "get_onboarding_status",
    "channels_section_status",
    "image_generation_section_status",
    "llm_section_status",
    "memory_embedding_section_status",
    "router_section_status",
    "search_section_status",
]
