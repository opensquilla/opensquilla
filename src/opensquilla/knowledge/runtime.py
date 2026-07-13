from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any

_INVALID_SNAPSHOT_MESSAGE = "invalid knowledge capability snapshot"
_CAPABILITIES_VERSION = re.compile("[0-9a-f]{16}")
_NEW_CONTRACT_MARKERS = frozenset(
    {
        "capabilitiesVersion",
        "configuredDefaultRetrievalProfile",
        "effectiveDefaultRetrievalProfile",
        "defaultFallbackReason",
    }
)
_REQUIRED_CONTRACT_FIELDS = frozenset(
    {
        "capabilitiesVersion",
        "configuredDefaultRetrievalProfile",
        "effectiveDefaultRetrievalProfile",
        "retrievalProfiles",
    }
)


class KnowledgeConnectionState(StrEnum):
    DISCONNECTED = "DISCONNECTED"
    DISCOVERING = "DISCOVERING"
    READY = "READY"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"
    LEGACY = "LEGACY"


@dataclass(frozen=True)
class RetrievalProfileCapability:
    id: str
    label: str
    kind: str
    available: bool
    reason: str | None = None
    model: str | None = None
    dimensions: int | None = None


@dataclass(frozen=True)
class KnowledgeCapabilitySnapshot:
    state: KnowledgeConnectionState
    capabilities_version: str | None
    profiles: tuple[RetrievalProfileCapability, ...]
    configured_default: str | None
    effective_default: str | None
    fallback_reason: str | None
    fetched_at_ms: int
    service_status: Mapping[str, Any]
    stale: bool = False
    legacy: bool = False

    @property
    def available_profile_ids(self) -> tuple[str, ...]:
        return tuple(profile.id for profile in self.profiles if profile.available)

    def to_status_wire(self) -> dict[str, Any]:
        status = dict(self.service_status)
        status["connectionState"] = self.state.value
        status["capabilitiesStale"] = self.stale
        status["capabilitiesFetchedAt"] = self.fetched_at_ms
        return status


def parse_capability_snapshot(
    payload: Mapping[str, Any],
    *,
    fetched_at_ms: int,
) -> KnowledgeCapabilitySnapshot:
    if not isinstance(payload, Mapping) or not _is_integer(fetched_at_ms):
        raise _invalid_snapshot()

    service_status = MappingProxyType(dict(payload))
    present_markers = _NEW_CONTRACT_MARKERS.intersection(payload)
    if not present_markers:
        return KnowledgeCapabilitySnapshot(
            state=KnowledgeConnectionState.LEGACY,
            capabilities_version=None,
            profiles=(),
            configured_default=None,
            effective_default=None,
            fallback_reason=None,
            fetched_at_ms=fetched_at_ms,
            service_status=service_status,
            legacy=True,
        )

    if not _REQUIRED_CONTRACT_FIELDS.issubset(payload):
        raise _invalid_snapshot()

    state = KnowledgeConnectionState.READY
    capabilities_version = _parse_capabilities_version(payload["capabilitiesVersion"])
    profiles = _parse_profiles(payload["retrievalProfiles"])
    configured_default = _required_text(payload["configuredDefaultRetrievalProfile"])
    effective_default = _optional_non_empty_text(
        payload["effectiveDefaultRetrievalProfile"]
    )
    fallback_reason = _optional_text(payload.get("defaultFallbackReason"))

    profiles_by_id = {profile.id: profile for profile in profiles}
    if len(profiles_by_id) != len(profiles):
        raise _invalid_snapshot()
    if configured_default not in profiles_by_id:
        raise _invalid_snapshot()
    if effective_default is not None:
        effective_profile = profiles_by_id.get(effective_default)
        if effective_profile is None or not effective_profile.available:
            raise _invalid_snapshot()

    return KnowledgeCapabilitySnapshot(
        state=state,
        capabilities_version=capabilities_version,
        profiles=profiles,
        configured_default=configured_default,
        effective_default=effective_default,
        fallback_reason=fallback_reason,
        fetched_at_ms=fetched_at_ms,
        service_status=service_status,
    )


def _parse_capabilities_version(value: Any) -> str:
    if not isinstance(value, str) or _CAPABILITIES_VERSION.fullmatch(value) is None:
        raise _invalid_snapshot()
    return value


def _parse_profiles(value: Any) -> tuple[RetrievalProfileCapability, ...]:
    if not isinstance(value, list):
        raise _invalid_snapshot()

    profiles = tuple(_parse_profile(profile) for profile in value)
    if len({profile.id for profile in profiles}) != len(profiles):
        raise _invalid_snapshot()
    return profiles


def _parse_profile(value: Any) -> RetrievalProfileCapability:
    if not isinstance(value, Mapping):
        raise _invalid_snapshot()

    profile_id = _required_text(value.get("id"))
    label = _required_text(value.get("label"))
    kind = _required_text(value.get("kind"))
    available = value.get("available")
    if not isinstance(available, bool):
        raise _invalid_snapshot()

    reason = _optional_text(value.get("reason"))
    model = _optional_text(value.get("model"))
    dimensions = value.get("dimensions")
    if dimensions is not None and not _is_integer(dimensions):
        raise _invalid_snapshot()

    return RetrievalProfileCapability(
        id=profile_id,
        label=label,
        kind=kind,
        available=available,
        reason=reason,
        model=model,
        dimensions=dimensions,
    )


def _required_text(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _invalid_snapshot()
    return value


def _optional_non_empty_text(value: Any) -> str | None:
    if value is None:
        return None
    return _required_text(value)


def _optional_text(value: Any) -> str | None:
    if value is not None and not isinstance(value, str):
        raise _invalid_snapshot()
    return value


def _is_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _invalid_snapshot() -> ValueError:
    return ValueError(_INVALID_SNAPSHOT_MESSAGE)
