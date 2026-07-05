"""Live credential/model probe + model discovery for LLM providers.

The cheapest class of misconfiguration — a bad API key, a typo'd model id, a
wrong base URL — used to surface only as an HTTP error in the middle of the
first chat. The probe runs a one-token chat turn against the candidate
configuration *before* it is saved, classifies any failure through the
standard provider taxonomy, and reports an actionable result.

Model discovery (:func:`discover_provider_models`) builds the same kind of
throwaway, never-persisted provider from candidate credentials and asks it
for its live model list, enriching each row from the layered model catalog.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import structlog

from opensquilla.provider.failures import ProviderFailureKind, classify_provider_error
from opensquilla.provider.registry import get_provider_spec
from opensquilla.provider.selector import (
    ProviderBuildError,
    _exception_status_code,
    build_provider,
)
from opensquilla.provider.types import ChatConfig, DoneEvent, ErrorEvent, Message, ModelInfo
from opensquilla.redaction import redact_error_text

log = structlog.get_logger(__name__)

_PROBE_TIMEOUT_SECONDS = 30.0


@dataclass(frozen=True)
class ProviderProbeResult:
    """Outcome of one live provider probe (never persisted)."""

    ok: bool
    provider_id: str
    model: str
    failure_kind: str = ""
    message: str = ""
    code: str = ""

    def to_payload(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "providerId": self.provider_id,
            "model": self.model,
            "failureKind": self.failure_kind,
            "message": self.message,
            "code": self.code,
        }


def _resolve_probe_api_key(api_key: str, api_key_env: str, spec_env_key: str) -> tuple[str, str]:
    """Return (key, source-description) using the config precedence."""
    if api_key.strip():
        return api_key.strip(), "explicit"
    env_name = api_key_env.strip() or spec_env_key.strip()
    if env_name and env_name != "OAuth":
        return os.environ.get(env_name, "").strip(), f"${env_name}"
    return "", ""


async def probe_llm_provider(
    *,
    provider_id: str,
    model: str,
    api_key: str = "",
    api_key_env: str = "",
    base_url: str = "",
    proxy: str = "",
    timeout: float = _PROBE_TIMEOUT_SECONDS,
) -> ProviderProbeResult:
    """Run a one-token live chat against the candidate provider config.

    Raises ``ValueError`` for validation-level problems (unknown provider id,
    missing model) so callers surface those as typed input errors; runtime
    reachability/credential failures come back as a not-ok result.
    """
    provider_id = (provider_id or "").strip()
    model = (model or "").strip()
    spec = get_provider_spec(provider_id)  # raises UnknownProviderError(ValueError)
    if not model:
        raise ValueError("Model is required for a provider probe.")
    if not spec.runtime_supported:
        raise ValueError(f"Provider '{provider_id}' has no runtime support to probe.")

    resolved_key, key_source = _resolve_probe_api_key(api_key, api_key_env, spec.env_key)
    if spec.requires_api_key() and not resolved_key:
        checked = key_source or (spec.env_key and f"${spec.env_key}") or "no env key"
        return ProviderProbeResult(
            ok=False,
            provider_id=provider_id,
            model=model,
            failure_kind=ProviderFailureKind.AUTH_INVALID.value,
            message=f"No API key available (checked {checked}).",
        )

    try:
        provider = build_provider(
            provider_id,
            model,
            api_key=resolved_key,
            base_url=base_url.strip(),
            proxy=proxy.strip(),
        )
    except ProviderBuildError as exc:
        return ProviderProbeResult(
            ok=False,
            provider_id=provider_id,
            model=model,
            failure_kind=ProviderFailureKind.BAD_REQUEST.value,
            message=str(exc),
        )

    cfg = ChatConfig(max_tokens=1, timeout=timeout, thinking=False)
    messages = [Message(role="user", content="ping")]
    try:
        async for event in provider.chat(messages, config=cfg):
            if isinstance(event, ErrorEvent):
                status_code = int(event.code) if str(event.code).isdigit() else None
                kind = classify_provider_error(
                    provider_id,
                    status_code,
                    raw_code=event.code,
                    message=event.message,
                )
                return ProviderProbeResult(
                    ok=False,
                    provider_id=provider_id,
                    model=model,
                    failure_kind=kind.value,
                    # Provider error bodies can echo credentials (bad keys,
                    # signed URLs) — never repeat them verbatim.
                    message=redact_error_text(event.message),
                    code=str(event.code),
                )
            if isinstance(event, DoneEvent):
                return ProviderProbeResult(ok=True, provider_id=provider_id, model=model)
    except Exception as exc:  # noqa: BLE001 - a probe never raises transport noise
        log.warning(
            "onboarding.provider_probe_failed",
            provider=provider_id,
            error=redact_error_text(str(exc)),
        )
        return ProviderProbeResult(
            ok=False,
            provider_id=provider_id,
            model=model,
            failure_kind=ProviderFailureKind.TRANSPORT_TRANSIENT.value,
            message=redact_error_text(str(exc)),
        )

    return ProviderProbeResult(
        ok=False,
        provider_id=provider_id,
        model=model,
        failure_kind=ProviderFailureKind.MALFORMED_RESPONSE.value,
        message="Provider stream ended without a completion event.",
    )


# ---------------------------------------------------------------------------
# Model discovery
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProviderModelsDiscoverResult:
    """Outcome of one live model-discovery call (never persisted).

    ``source`` distinguishes a provider that genuinely listed models
    (``"live"``) from one that lists nothing or does not support listing
    (``"none"``, still ``ok=True``) — a classified failure is ``ok=False``
    with ``failure_kind``/``detail`` set instead.
    """

    ok: bool
    provider_id: str
    failure_kind: str = ""
    detail: str = ""
    source: str = "none"  # "live" | "none"
    models: list[dict[str, object]] = field(default_factory=list)

    def to_payload(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "failureKind": self.failure_kind,
            "detail": self.detail,
            "source": self.source,
            "models": [dict(m) for m in self.models],
        }


def _discover_model_row(info: ModelInfo, provider_id: str) -> dict[str, object]:
    """Adapt one live ``ModelInfo`` row, filling gaps from the layered catalog.

    The provider's own listing wins per field where it genuinely knows a
    value (``> 0`` limits, positive prices); ``shared_catalog().resolve_entry``
    fills the rest. ``capabilitySource`` names the catalog layer that resolved
    the entry, so clients can tell curated metadata from synthesized floors.
    """
    from opensquilla.provider.model_catalog import shared_catalog

    entry = shared_catalog().resolve_entry(info.model_id, provider=provider_id)
    context_window = info.context_window if info.context_window > 0 else entry.context_window
    max_output = (
        info.max_output_tokens if info.max_output_tokens > 0 else entry.max_output_tokens
    )
    capabilities: list[str] = ["chat"]
    if info.supports_tools or entry.supports_tools:
        capabilities.append("tools")
    if info.supports_reasoning or entry.supports_reasoning:
        capabilities.append("reasoning")
    if info.supports_vision or entry.supports_vision:
        capabilities.append("vision")

    pricing: dict[str, float] | None = None
    if info.input_cost_per_1k > 0 or info.output_cost_per_1k > 0:
        pricing = {
            "inputPer1k": info.input_cost_per_1k,
            "outputPer1k": info.output_cost_per_1k,
        }
    elif entry.input_cost_per_mtok is not None or entry.output_cost_per_mtok is not None:
        # Catalog costs are canonical per-Mtok; the wire stays per-1k for
        # parity with models.list pricing rows.
        pricing = {
            "inputPer1k": (entry.input_cost_per_mtok or 0.0) / 1000.0,
            "outputPer1k": (entry.output_cost_per_mtok or 0.0) / 1000.0,
        }

    return {
        "id": info.model_id,
        "name": info.display_name or info.model_id,
        "contextWindow": context_window,
        "maxOutputTokens": max_output,
        "capabilities": capabilities,
        "pricing": pricing,
        "capabilitySource": entry.source,
    }


async def discover_provider_models(
    *,
    provider_id: str,
    api_key: str = "",
    api_key_env: str = "",
    base_url: str = "",
    proxy: str = "",
) -> ProviderModelsDiscoverResult:
    """List a candidate provider's live models without persisting anything.

    Builds the same throwaway provider as :func:`probe_llm_provider` (no
    model id is needed to list models) and classifies failures through the
    exact machinery ``ModelSelector.list_models_detailed`` uses, so a wrong
    key and an empty catalog stay distinguishable.

    Raises ``ValueError`` for validation-level problems (unknown provider id,
    no runtime support) so callers surface those as typed input errors.
    """
    provider_id = (provider_id or "").strip()
    spec = get_provider_spec(provider_id)  # raises UnknownProviderError(ValueError)
    if not spec.runtime_supported:
        raise ValueError(f"Provider '{provider_id}' has no runtime support to discover.")

    resolved_key, key_source = _resolve_probe_api_key(api_key, api_key_env, spec.env_key)
    if spec.requires_api_key() and not resolved_key:
        checked = key_source or (spec.env_key and f"${spec.env_key}") or "no env key"
        return ProviderModelsDiscoverResult(
            ok=False,
            provider_id=provider_id,
            failure_kind=ProviderFailureKind.AUTH_INVALID.value,
            detail=f"No API key available (checked {checked}).",
        )

    try:
        provider = build_provider(
            provider_id,
            "",  # listing models needs no bound model id
            api_key=resolved_key,
            base_url=base_url.strip(),
            proxy=proxy.strip(),
        )
    except ProviderBuildError as exc:
        return ProviderModelsDiscoverResult(
            ok=False,
            provider_id=provider_id,
            failure_kind=ProviderFailureKind.BAD_REQUEST.value,
            detail=str(exc),
        )

    try:
        provider_models = await provider.list_models()
    except Exception as exc:  # noqa: BLE001 - same classification as list_models_detailed
        kind = classify_provider_error(
            provider_id,
            _exception_status_code(exc),
            message=str(exc),
        )
        log.warning(
            "onboarding.models_discover_failed",
            provider=provider_id,
            kind=kind.value,
            error=redact_error_text(str(exc)),
        )
        return ProviderModelsDiscoverResult(
            ok=False,
            provider_id=provider_id,
            failure_kind=kind.value,
            # Provider error bodies can echo credentials (bad keys, signed
            # URLs) — never repeat them verbatim.
            detail=redact_error_text(str(exc)),
        )

    if not provider_models:
        # Distinct from a classified failure: the provider answered but lists
        # nothing (or does not support listing) — ok, just no live source.
        return ProviderModelsDiscoverResult(ok=True, provider_id=provider_id, source="none")
    return ProviderModelsDiscoverResult(
        ok=True,
        provider_id=provider_id,
        source="live",
        models=[_discover_model_row(m, provider_id) for m in provider_models],
    )
