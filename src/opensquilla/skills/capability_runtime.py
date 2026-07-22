"""Resolve provider-backed capability connections for trusted consumers.

This bridge deliberately sits above the generic provider registry.  A skill
consumer asks for a capability; code-owned adapter metadata decides which
provider deployment may satisfy it.  The public status never contains
credential material, while the execution lease keeps the complete atomic
connection (provider, key, endpoint, proxy) in memory only.

No new persisted configuration is introduced here.  Existing active LLM,
secondary provider-profile, legacy image-provider, and canonical environment
configuration remain compatible inputs.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlsplit

from opensquilla.endpoint_identity import base_url_allows_credential_reuse
from opensquilla.provider.environment import environment_value
from opensquilla.provider.registry import UnknownProviderError, get_provider_spec
from opensquilla.provider.selector import ProviderConfig
from opensquilla.skills.types import SkillLayer

CAPABILITY_IMAGE_REFERENCE = "image.generate.reference"
CAPABILITY_VIDEO_GENERATE = "video.generate"

META_CAPABILITY_PROVIDER_ENV = "OPENSQUILLA_META_CAPABILITY_PROVIDER"
META_CAPABILITY_API_KEY_ENV = "OPENSQUILLA_META_CAPABILITY_API_KEY"
META_CAPABILITY_BASE_URL_ENV = "OPENSQUILLA_META_CAPABILITY_BASE_URL"
META_CAPABILITY_PROXY_ENV = "OPENSQUILLA_META_CAPABILITY_PROXY"

# Parent-process-only metadata carried beside the trusted child environment.
# The skill executor consumes these names before subprocess construction; they
# are never placed in the child environment, argv, run inputs, or transcripts.
META_CAPABILITY_INTERNAL_CREDENTIAL_SOURCE = "__opensquilla_meta_credential_source"
META_CAPABILITY_INTERNAL_CREDENTIAL_LEASE_TOKEN = (
    "__opensquilla_meta_credential_lease_token"
)
META_CAPABILITY_INTERNAL_PROVIDER = "__opensquilla_meta_provider"
META_CAPABILITY_INTERNAL_SESSION_KEY = "__opensquilla_meta_session_key"

# Compatibility name accepted by the current bundled clients and older saved
# tests/plans.  New runtime wiring also sends the provider-neutral tuple above.
META_OPENROUTER_API_KEY_ENV = "OPENSQUILLA_META_OPENROUTER_API_KEY"

_OPENROUTER_DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
_TRUSTED_META_CAPABILITY_PARENT = "meta-short-drama"
_TRUSTED_META_CAPABILITY_CONSUMERS = (
    "nano-banana-pro",
    "seedance-2-prompt",
)
_CONSENT_PROCEED_WHEN = "'DECISION: proceed' in outputs.review_normalize"


@dataclass(frozen=True)
class CapabilityRequirement:
    """One provider-backed operation required by a trusted consumer."""

    capability_id: str
    consumer: str
    provider_id: str
    model: str
    portable_env_aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class CapabilityConnectionStatus:
    """Secret-free status for settings/readiness surfaces."""

    requirement: CapabilityRequirement
    ready: bool
    reason_code: str = ""
    connection_source: str = "none"
    credential_source: str = "none"
    credential_env: str = ""
    endpoint_source: str = "none"
    proxy_source: str = "none"

    @property
    def provider_id(self) -> str:
        return self.requirement.provider_id


@dataclass(frozen=True)
class CapabilityConnectionLease:
    """In-memory execution connection; never serialize or persist this value."""

    status: CapabilityConnectionStatus
    api_key: str = field(default="", repr=False)
    base_url: str = field(default="", repr=False)
    proxy: str = field(default="", repr=False)
    credential_pool_lease_token: str = field(default="", repr=False, compare=False)

    @property
    def ready(self) -> bool:
        return self.status.ready and bool(self.api_key and self.base_url)


@dataclass(frozen=True)
class _ActiveProviderResolution:
    """Active provider tuple plus non-secret runtime credential provenance."""

    provider_config: ProviderConfig
    credential_source: str = "inherited"
    credential_env: str = ""
    credential_endpoint: str = ""
    base_url_from_env: bool = False


# Exact bundled consumers only.  Workspace/project skills cannot opt themselves
# into this map and therefore cannot receive a provider credential by declaring
# a lookalike capability in untrusted frontmatter.
_CONSUMER_REQUIREMENTS: dict[str, tuple[CapabilityRequirement, ...]] = {
    "nano-banana-pro": (
        CapabilityRequirement(
            capability_id=CAPABILITY_IMAGE_REFERENCE,
            consumer="nano-banana-pro",
            provider_id="openrouter",
            model="google/gemini-3.1-flash-image-preview",
            portable_env_aliases=("OPENROUTER_API_KEY",),
        ),
    ),
    "seedance-2-prompt": (
        CapabilityRequirement(
            capability_id=CAPABILITY_VIDEO_GENERATE,
            consumer="seedance-2-prompt",
            provider_id="openrouter",
            model="bytedance/seedance-2.0",
            portable_env_aliases=("OPENROUTER_API_KEY",),
        ),
    ),
}


def _trusted_paid_step_contracts() -> dict[str, tuple[str, str]]:
    """Return the code-owned paid-step allowlist for the short-drama plan."""

    contracts = {
        "reference_image": ("nano-banana-pro", _CONSENT_PROCEED_WHEN),
    }
    for shot in range(1, 11):
        present = (
            f"{_CONSENT_PROCEED_WHEN} and "
            f"'=== SHOT_{shot} ===' in outputs.final_script.splitlines()"
        )
        contracts[f"shot{shot}_image"] = (
            "nano-banana-pro",
            f"{present} and '__SHOT_ABSENT__' not in outputs.shot{shot}_img_prompt",
        )
        contracts[f"shot{shot}_video"] = (
            "seedance-2-prompt",
            f"{present} and '__SHOT_ABSENT__' not in outputs.shot{shot}_vid_prompt",
        )
    return contracts


_TRUSTED_PAID_STEP_CONTRACTS = _trusted_paid_step_contracts()


def trusted_capability_consumers_for_meta_plan(
    parent_spec: Any,
    plan: Any,
) -> tuple[str, ...]:
    """Authorize provider leases only for the exact code-owned workflow.

    A bundled child is not an authority: workspace, project, personal, and
    managed parents may legitimately compose bundled skills, but they must not
    inherit a Gateway credential.  The parent layer/name and every paid step's
    identity, execution kind, paid-side-effect marker, and post-review consent
    condition are therefore checked together against a code-owned allowlist.
    Any drift fails closed and yields no consumers.
    """

    if (
        getattr(parent_spec, "name", None) != _TRUSTED_META_CAPABILITY_PARENT
        or getattr(parent_spec, "kind", None) != "meta"
        or getattr(parent_spec, "layer", None) != SkillLayer.BUNDLED
        or bool(getattr(parent_spec, "disable_model_invocation", False))
        or getattr(plan, "name", None) != _TRUSTED_META_CAPABILITY_PARENT
    ):
        return ()

    raw_steps = getattr(plan, "steps", None)
    if not isinstance(raw_steps, tuple):
        return ()

    capability_names = frozenset(_TRUSTED_META_CAPABILITY_CONSUMERS)
    matched: set[str] = set()
    seen_ids: set[str] = set()
    for step in raw_steps:
        step_id = _text(getattr(step, "id", ""))
        if not step_id or step_id in seen_ids:
            return ()
        seen_ids.add(step_id)

        routes = getattr(step, "route", ())
        if not isinstance(routes, tuple):
            return ()
        if any(_text(getattr(route, "to", "")) in capability_names for route in routes):
            # A conditional route could otherwise smuggle a paid consumer into
            # an unrelated, unreviewed step id.
            return ()

        skill = _text(getattr(step, "skill", ""))
        if skill not in capability_names:
            continue
        expected = _TRUSTED_PAID_STEP_CONTRACTS.get(step_id)
        if expected is None:
            return ()
        expected_skill, expected_when = expected
        if (
            skill != expected_skill
            or getattr(step, "kind", None) != "skill_exec"
            or getattr(step, "side_effect", None) != "external_paid_submit"
            or getattr(step, "when", None) != expected_when
            or routes
        ):
            return ()
        matched.add(step_id)

    if matched != set(_TRUSTED_PAID_STEP_CONTRACTS):
        return ()
    return _TRUSTED_META_CAPABILITY_CONSUMERS


def capability_requirements_for_consumers(
    consumers: Iterable[str],
) -> tuple[CapabilityRequirement, ...]:
    """Return stable, de-duplicated requirements for trusted consumers."""

    requirements: dict[tuple[str, str, str], CapabilityRequirement] = {}
    for consumer in consumers:
        for requirement in _CONSUMER_REQUIREMENTS.get(str(consumer), ()):
            key = (
                requirement.provider_id,
                requirement.capability_id,
                requirement.consumer,
            )
            requirements.setdefault(key, requirement)
    return tuple(requirements[key] for key in sorted(requirements))


def capability_manifest_env_aliases_for_consumers(
    consumers: Iterable[str],
) -> tuple[str, ...]:
    """Return portable CLI env names superseded by trusted parent wiring."""

    return tuple(
        sorted(
            {
                alias
                for requirement in capability_requirements_for_consumers(consumers)
                for alias in requirement.portable_env_aliases
                if alias
            }
        )
    )


def capability_provider_display_name(provider_id: str) -> str:
    """Return a stable human label without adding UI-owned provider tables."""

    normalized = _text(provider_id).lower()
    try:
        policy_label = _text(get_provider_spec(normalized).compat.display_name)
    except UnknownProviderError:
        policy_label = ""
    if policy_label and policy_label.lower() != "provider":
        return policy_label
    return " ".join(
        part[:1].upper() + part[1:]
        for part in normalized.replace("_", "-").replace(".", "-").split("-")
        if part
    )


def _text(value: Any) -> str:
    return str(value or "").strip()


def _valid_http_base_url(value: str) -> bool:
    raw = _text(value)
    if not raw or any(char.isspace() or ord(char) < 0x20 for char in raw):
        return False
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except (UnicodeError, ValueError):
        return False
    return bool(
        parsed.scheme.lower() in {"http", "https"}
        and parsed.hostname
        and parsed.username is None
        and parsed.password is None
        and not parsed.query
        and not parsed.fragment
        and "\\" not in parsed.netloc
        and (port is None or 0 < port <= 65535)
    )


def _valid_http_proxy_url(value: str) -> bool:
    """Apply the bundled provider clients' provider-neutral proxy rules."""

    raw = _text(value)
    if not raw or any(char.isspace() or ord(char) < 0x20 for char in raw):
        return False
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except (UnicodeError, ValueError):
        return False
    return bool(
        parsed.scheme.lower() in {"http", "https"}
        and parsed.hostname
        and not parsed.query
        and not parsed.fragment
        and "\\" not in parsed.netloc
        and (port is None or 0 < port <= 65535)
    )


def _copy_config(config: Any) -> Any:
    copier = getattr(config, "model_copy", None)
    if callable(copier):
        return copier(deep=True)
    return config


def _active_provider_config(
    config: Any,
    *,
    model: str,
) -> _ActiveProviderResolution | None:
    llm = getattr(config, "llm", None)
    provider = _text(getattr(llm, "provider", "")).lower()
    if not provider:
        return None

    try:
        spec = get_provider_spec(provider)
    except UnknownProviderError:
        spec = None
    canonical_env = _text(getattr(spec, "env_key", ""))
    configured_env = _text(getattr(llm, "api_key_env", ""))
    credential_env = configured_env or canonical_env

    # GatewayConfig has provenance-aware environment materialisation.  Use it
    # on a copy so readiness never mutates the live config.  Lightweight test
    # doubles take the equivalent, dependency-free path below.
    if callable(getattr(config, "model_copy", None)):
        from opensquilla.gateway.llm_runtime import resolve_llm_runtime_config

        runtime = resolve_llm_runtime_config(_copy_config(config))
        credential_from_env = bool(runtime.api_key_from_env and credential_env)
        credential_source = "inherited"
        if credential_from_env:
            credential_source = (
                "registry_env" if credential_env == canonical_env else "active_env"
            )
        return _ActiveProviderResolution(
            provider_config=ProviderConfig(
                provider=runtime.provider,
                model=_text(runtime.model) or model,
                api_key=_text(runtime.api_key),
                base_url=_text(runtime.base_url),
                proxy=_text(runtime.proxy),
                provider_routing=dict(runtime.provider_routing or {}),
            ),
            credential_source=credential_source,
            credential_env=credential_env if credential_from_env else "",
            credential_endpoint=(
                _text(getattr(spec, "default_base_url", ""))
                if credential_from_env and credential_env == canonical_env
                else _text(runtime.base_url)
            ),
            base_url_from_env=bool(runtime.base_url_from_env),
        )

    api_key = _text(getattr(llm, "api_key", ""))
    credential_from_env = False
    if not api_key:
        if credential_env and credential_env != "OAuth":
            api_key = environment_value(credential_env).strip()
            credential_from_env = bool(api_key)
    base_url = _text(getattr(llm, "base_url", "")) or _text(
        getattr(spec, "default_base_url", "")
    )
    proxy = environment_value("OPENSQUILLA_LLM_PROXY").strip() or _text(
        getattr(llm, "proxy", "")
    )
    credential_source = "inherited"
    if credential_from_env:
        credential_source = (
            "registry_env" if credential_env == canonical_env else "active_env"
        )
    return _ActiveProviderResolution(
        provider_config=ProviderConfig(
            provider=provider,
            model=_text(getattr(llm, "model", "")) or model,
            api_key=api_key,
            base_url=base_url,
            proxy=proxy,
            provider_routing=dict(getattr(llm, "provider_routing", {}) or {}),
        ),
        credential_source=credential_source,
        credential_env=credential_env if credential_from_env else "",
        credential_endpoint=(
            _text(getattr(spec, "default_base_url", ""))
            if credential_from_env and credential_env == canonical_env
            else base_url
        ),
    )


def _active_credential_endpoint_mismatch(
    active: _ActiveProviderResolution | None,
    requirement: CapabilityRequirement,
) -> bool:
    """Reject a bare registry key paired with an explicit foreign origin."""

    if active is None or active.credential_source != "registry_env":
        return False
    provider_config = active.provider_config
    return bool(
        _text(provider_config.provider).lower() == requirement.provider_id
        and not active.base_url_from_env
        and not base_url_allows_credential_reuse(
            active.credential_endpoint,
            _text(provider_config.base_url),
        )
    )


def _connection_source(credential_source: str) -> str:
    if credential_source == "inherited":
        return "active_llm"
    if credential_source.startswith("profile"):
        return "llm_profile"
    if credential_source == "registry_env":
        return "environment"
    if credential_source == "keyless":
        return "provider_registry"
    return "provider_deployment"


def _status_from_resolution(
    requirement: CapabilityRequirement,
    resolution: Any,
) -> CapabilityConnectionStatus:
    provider_config = getattr(resolution, "provider_config", None)
    base_url = _text(getattr(provider_config, "base_url", ""))
    proxy = _text(getattr(provider_config, "proxy", ""))
    reason = _text(getattr(resolution, "reason", ""))
    ready = bool(getattr(resolution, "ready", False))
    if proxy and not _valid_http_proxy_url(proxy):
        ready = False
        reason = "invalid_proxy"
    elif ready and not _valid_http_base_url(base_url):
        ready = False
        reason = "invalid_endpoint"
    return CapabilityConnectionStatus(
        requirement=requirement,
        ready=ready,
        reason_code=reason,
        connection_source=_connection_source(
            _text(getattr(resolution, "credential_source", "none"))
        ),
        credential_source=_text(getattr(resolution, "credential_source", "none")),
        credential_env=_text(getattr(resolution, "credential_env", "")),
        endpoint_source=_text(getattr(resolution, "endpoint_source", "none")),
        proxy_source=_text(getattr(resolution, "proxy_source", "none")),
    )


def _profile_pool_acquirer(*, acquire: bool):
    if acquire:
        from opensquilla.engine.selector_override import acquire_profile_credential

        return acquire_profile_credential
    from opensquilla.engine.selector_override import peek_profile_credential

    return peek_profile_credential


def _legacy_openrouter_connection(
    config: Any,
    requirement: CapabilityRequirement,
) -> CapabilityConnectionLease | None:
    image_config = getattr(config, "image_generation", None)
    providers = getattr(image_config, "providers", None)
    provider_config = getattr(providers, "openrouter", None)
    if provider_config is None:
        return None

    raw_fields_set: object = getattr(provider_config, "model_fields_set", set())
    fields_set: set[str] = (
        {str(field) for field in raw_fields_set}
        if isinstance(raw_fields_set, set)
        else set()
    )
    base_url = _text(getattr(provider_config, "base_url", "")) or _OPENROUTER_DEFAULT_BASE_URL
    explicit_key = _text(getattr(provider_config, "api_key", ""))
    env_name = _text(getattr(provider_config, "api_key_env", "")) or "OPENROUTER_API_KEY"
    env_is_explicit = "api_key_env" in fields_set or env_name != "OPENROUTER_API_KEY"
    base_is_explicit = "base_url" in fields_set or base_url != _OPENROUTER_DEFAULT_BASE_URL

    key = explicit_key
    credential_source = "legacy_image_config" if key else "none"
    credential_env = ""
    if not key and env_is_explicit:
        key = environment_value(env_name).strip()
        if key:
            credential_source = "legacy_image_env"
            credential_env = env_name
    if not key and not base_is_explicit:
        key = environment_value("OPENROUTER_API_KEY").strip()
        if key:
            credential_source = "registry_env"
            credential_env = "OPENROUTER_API_KEY"

    reason = ""
    if not _valid_http_base_url(base_url):
        reason = "invalid_endpoint"
    elif not key:
        reason = "missing_credential"
    status = CapabilityConnectionStatus(
        requirement=requirement,
        ready=not reason,
        reason_code=reason,
        connection_source="legacy_image_generation",
        credential_source=credential_source,
        credential_env=credential_env,
        endpoint_source="legacy_image_generation",
        proxy_source="none",
    )
    return CapabilityConnectionLease(status=status, api_key=key, base_url=base_url)


def _resolve_capability_connection(
    config: Any | None,
    requirement: CapabilityRequirement,
    *,
    acquire: bool,
    session_key: str,
) -> CapabilityConnectionLease:
    from opensquilla.provider.deployment import resolve_provider_deployment

    effective_config = config or SimpleNamespace(
        llm=SimpleNamespace(provider="", proxy=""),
        llm_profiles={},
    )
    active = _active_provider_config(effective_config, model=requirement.model)
    resolution = resolve_provider_deployment(
        effective_config,
        requirement.provider_id,
        requirement.model,
        inherited_provider_config=(active.provider_config if active is not None else None),
        session_key=session_key,
        credential_pool_acquirer=_profile_pool_acquirer(acquire=acquire),
    )
    status = _status_from_resolution(requirement, resolution)
    active_endpoint_mismatch = _active_credential_endpoint_mismatch(active, requirement)
    if (
        active is not None
        and active.credential_source != "inherited"
        and _text(active.provider_config.provider).lower() == requirement.provider_id
    ):
        status = CapabilityConnectionStatus(
            requirement=requirement,
            ready=status.ready,
            reason_code=status.reason_code,
            connection_source="active_llm",
            credential_source=active.credential_source,
            credential_env=active.credential_env,
            endpoint_source=status.endpoint_source,
            proxy_source=status.proxy_source,
        )
    if active_endpoint_mismatch and status.ready:
        status = CapabilityConnectionStatus(
            requirement=requirement,
            ready=False,
            reason_code="credential_endpoint_mismatch",
            connection_source="active_llm",
            credential_source="registry_env",
            credential_env=active.credential_env if active is not None else "",
            endpoint_source=status.endpoint_source,
            proxy_source=status.proxy_source,
        )
    provider_config = getattr(resolution, "provider_config", None)
    if status.ready and provider_config is not None:
        resolved_lease = CapabilityConnectionLease(
            status=status,
            api_key=_text(getattr(provider_config, "api_key", "")),
            base_url=_text(getattr(provider_config, "base_url", "")),
            proxy=_text(getattr(provider_config, "proxy", "")),
            credential_pool_lease_token=_text(
                getattr(resolution, "credential_pool_lease_token", "")
            ),
        )
        # Preserve active/profile precedence, but let an explicitly configured
        # legacy media connection outrank a bare canonical environment key.
        if (
            requirement.provider_id == "openrouter"
            and status.credential_source == "registry_env"
        ):
            legacy = _legacy_openrouter_connection(effective_config, requirement)
            if (
                legacy is not None
                and legacy.ready
                and legacy.status.credential_source != "registry_env"
            ):
                return legacy
        return resolved_lease

    # This is an invalid active-provider tuple, not an absent provider.  Do
    # not silently route around it through the legacy media section: the user
    # must explicitly pair the custom endpoint with its own credential.
    if status.reason_code in {"invalid_endpoint", "invalid_proxy"} or (
        active_endpoint_mismatch
        and status.reason_code == "credential_endpoint_mismatch"
    ):
        return CapabilityConnectionLease(status=status)

    # Compatibility bridge for installations that configured the former
    # image-generation section but have not yet created an LLM profile.  The
    # key and endpoint are taken as one tuple; a canonical OpenRouter env key
    # never follows an unrelated custom legacy endpoint.
    if requirement.provider_id == "openrouter":
        legacy = _legacy_openrouter_connection(effective_config, requirement)
        if legacy is not None and legacy.ready:
            return legacy
    return CapabilityConnectionLease(status=status)


def resolve_capability_status(
    config: Any | None,
    requirement: CapabilityRequirement,
) -> CapabilityConnectionStatus:
    """Resolve a non-mutating, secret-free capability readiness status."""

    return _resolve_capability_connection(
        config,
        requirement,
        acquire=False,
        session_key="meta-capability-readiness",
    ).status


def lease_capability_connection(
    config: Any | None,
    requirement: CapabilityRequirement,
    *,
    session_key: str,
) -> CapabilityConnectionLease:
    """Acquire the in-memory connection used by one MetaSkill run."""

    return _resolve_capability_connection(
        config,
        requirement,
        acquire=True,
        session_key=session_key or "meta-capability-runtime",
    )


def capability_runtime_env_for_consumers(
    config: Any | None,
    consumers: Iterable[str],
    *,
    parent_spec: Any,
    plan: Any,
    session_key: str,
) -> dict[str, dict[str, str]]:
    """Build child environments only for a validated trusted parent plan."""

    authorized = trusted_capability_consumers_for_meta_plan(parent_spec, plan)
    requested = tuple(dict.fromkeys(_text(consumer) for consumer in consumers))
    if not authorized:
        return {}

    requirements = capability_requirements_for_consumers(
        consumer for consumer in requested if consumer in authorized
    )
    leases: dict[str, CapabilityConnectionLease] = {}
    result: dict[str, dict[str, str]] = {}
    for requirement in requirements:
        lease = leases.get(requirement.provider_id)
        if lease is None:
            lease = lease_capability_connection(
                config,
                requirement,
                session_key=session_key,
            )
            leases[requirement.provider_id] = lease
        if not lease.ready:
            continue
        values = {
            META_CAPABILITY_PROVIDER_ENV: requirement.provider_id,
            META_CAPABILITY_API_KEY_ENV: lease.api_key,
            META_CAPABILITY_BASE_URL_ENV: lease.base_url,
        }
        if lease.proxy:
            values[META_CAPABILITY_PROXY_ENV] = lease.proxy
        if requirement.provider_id == "openrouter":
            values[META_OPENROUTER_API_KEY_ENV] = lease.api_key
        if (
            lease.status.credential_source == "profile_pool"
            and lease.credential_pool_lease_token
        ):
            values.update(
                {
                    META_CAPABILITY_INTERNAL_CREDENTIAL_SOURCE: "profile_pool",
                    META_CAPABILITY_INTERNAL_CREDENTIAL_LEASE_TOKEN: (
                        lease.credential_pool_lease_token
                    ),
                    META_CAPABILITY_INTERNAL_PROVIDER: requirement.provider_id,
                    META_CAPABILITY_INTERNAL_SESSION_KEY: (
                        session_key or "meta-capability-runtime"
                    ),
                }
            )
        result[requirement.consumer] = values
    return result


__all__ = [
    "CAPABILITY_IMAGE_REFERENCE",
    "CAPABILITY_VIDEO_GENERATE",
    "META_CAPABILITY_API_KEY_ENV",
    "META_CAPABILITY_BASE_URL_ENV",
    "META_CAPABILITY_INTERNAL_CREDENTIAL_LEASE_TOKEN",
    "META_CAPABILITY_INTERNAL_CREDENTIAL_SOURCE",
    "META_CAPABILITY_INTERNAL_PROVIDER",
    "META_CAPABILITY_INTERNAL_SESSION_KEY",
    "META_CAPABILITY_PROVIDER_ENV",
    "META_CAPABILITY_PROXY_ENV",
    "META_OPENROUTER_API_KEY_ENV",
    "CapabilityConnectionLease",
    "CapabilityConnectionStatus",
    "CapabilityRequirement",
    "capability_requirements_for_consumers",
    "capability_provider_display_name",
    "capability_manifest_env_aliases_for_consumers",
    "capability_runtime_env_for_consumers",
    "lease_capability_connection",
    "resolve_capability_status",
    "trusted_capability_consumers_for_meta_plan",
]
