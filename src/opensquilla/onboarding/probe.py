"""Live credential/model probe for LLM providers.

The cheapest class of misconfiguration — a bad API key, a typo'd model id, a
wrong base URL — used to surface only as an HTTP error in the middle of the
first chat. The probe runs a one-token chat turn against the candidate
configuration *before* it is saved, classifies any failure through the
standard provider taxonomy, and reports an actionable result.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import structlog

from opensquilla.provider.failures import ProviderFailureKind, classify_provider_error
from opensquilla.provider.registry import get_provider_spec
from opensquilla.provider.selector import ProviderBuildError, build_provider
from opensquilla.provider.types import ChatConfig, DoneEvent, ErrorEvent, Message
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
