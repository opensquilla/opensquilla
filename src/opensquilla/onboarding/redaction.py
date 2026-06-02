"""Secret-aware redaction helpers used by mutations, RPC, and CLI output."""

from __future__ import annotations

from typing import Any

from opensquilla.onboarding.channel_specs import get_channel_setup_spec

REDACTED_PLACEHOLDER = "***"

_PROVIDER_SECRET_FIELDS = frozenset({"api_key"})


def redact_provider_payload(payload: dict[str, Any]) -> dict[str, Any]:
    out = dict(payload)
    for key in _PROVIDER_SECRET_FIELDS:
        if key in out and out[key]:
            out[key] = REDACTED_PLACEHOLDER
    return out


def redact_search_payload(payload: dict[str, Any]) -> dict[str, Any]:
    out = dict(payload)
    if out.get("api_key"):
        out["api_key"] = REDACTED_PLACEHOLDER
    return out


def redact_image_generation_payload(payload: dict[str, Any]) -> dict[str, Any]:
    out = dict(payload)
    if out.get("api_key"):
        out["api_key"] = REDACTED_PLACEHOLDER
    return out


def redact_audio_payload(payload: dict[str, Any]) -> dict[str, Any]:
    out = dict(payload)
    if out.get("api_key"):
        out["api_key"] = REDACTED_PLACEHOLDER
    return out


def redact_memory_embedding_payload(payload: dict[str, Any]) -> dict[str, Any]:
    out = dict(payload)
    if out.get("api_key"):
        out["api_key"] = REDACTED_PLACEHOLDER
    remote = out.get("remote")
    if isinstance(remote, dict) and remote.get("api_key"):
        remote = dict(remote)
        remote["api_key"] = REDACTED_PLACEHOLDER
        out["remote"] = remote
    return out


def redact_channel_entry(type_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        spec = get_channel_setup_spec(type_name)
    except KeyError:
        return dict(payload)
    secret_names = {f.name for f in spec.fields if f.secret}
    out = dict(payload)
    for key in secret_names:
        if key in out and out[key]:
            out[key] = REDACTED_PLACEHOLDER
    return out
