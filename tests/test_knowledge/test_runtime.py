from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError
from typing import Any, cast

import pytest

from opensquilla.knowledge.runtime import (
    KnowledgeCapabilitySnapshot,
    KnowledgeConnectionState,
    RetrievalProfileCapability,
    parse_capability_snapshot,
)

FULL_STATUS: dict[str, Any] = {
    "capabilitiesVersion": "0123456789abcdef",
    "configuredDefaultRetrievalProfile": "hybrid_rrf_bge_m3_fts5",
    "effectiveDefaultRetrievalProfile": "sqlite_fts5_default",
    "defaultFallbackReason": "embedding model is warming up",
    "defaultRetrievalProfile": "legacy_default",
    "retrievalProfiles": [
        {
            "id": "sqlite_fts5_default",
            "label": "SQLite FTS5",
            "kind": "lexical",
            "available": True,
            "reason": None,
        },
        {
            "id": "hybrid_rrf_bge_m3_fts5",
            "label": "Hybrid RRF",
            "kind": "hybrid",
            "available": True,
            "model": "BAAI/bge-m3",
            "dimensions": 1024,
        },
        {
            "id": "vector_unavailable",
            "label": "Unavailable vector",
            "kind": "vector",
            "available": False,
            "reason": "model unavailable",
        },
    ],
    "documentsIndexed": 3,
}

INVALID_SNAPSHOT_MESSAGE = "invalid knowledge capability snapshot"


def _full_status(**overrides: Any) -> dict[str, Any]:
    status = deepcopy(FULL_STATUS)
    status.update(overrides)
    return status


def _assert_invalid(status: Any, *, fetched_at_ms: Any = 1234) -> None:
    with pytest.raises(ValueError) as raised:
        parse_capability_snapshot(status, fetched_at_ms=fetched_at_ms)

    assert str(raised.value) == INVALID_SNAPSHOT_MESSAGE
    assert repr(raised.value) == f"ValueError({INVALID_SNAPSHOT_MESSAGE!r})"


def test_parse_capability_snapshot_returns_complete_ready_snapshot() -> None:
    snapshot = parse_capability_snapshot(FULL_STATUS, fetched_at_ms=1234)

    assert isinstance(snapshot, KnowledgeCapabilitySnapshot)
    assert snapshot.state is KnowledgeConnectionState.READY
    assert snapshot.capabilities_version == "0123456789abcdef"
    assert snapshot.available_profile_ids == (
        "sqlite_fts5_default",
        "hybrid_rrf_bge_m3_fts5",
    )
    assert snapshot.configured_default == "hybrid_rrf_bge_m3_fts5"
    assert snapshot.effective_default == "sqlite_fts5_default"
    assert snapshot.fallback_reason == "embedding model is warming up"
    assert snapshot.fetched_at_ms == 1234
    assert snapshot.stale is False
    assert snapshot.legacy is False
    assert snapshot.profiles[1] == RetrievalProfileCapability(
        id="hybrid_rrf_bge_m3_fts5",
        label="Hybrid RRF",
        kind="hybrid",
        available=True,
        model="BAAI/bge-m3",
        dimensions=1024,
    )
    assert snapshot.to_status_wire()["connectionState"] == "READY"
    assert snapshot.to_status_wire()["documentsIndexed"] == 3


def test_snapshot_copies_top_level_status_and_exposes_immutable_values() -> None:
    status = _full_status()
    snapshot = parse_capability_snapshot(status, fetched_at_ms=1234)
    status["documentsIndexed"] = 99

    assert type(snapshot.service_status).__name__ == "mappingproxy"
    assert snapshot.service_status["documentsIndexed"] == 3
    assert isinstance(snapshot.profiles, tuple)

    with pytest.raises(TypeError):
        snapshot.service_status["documentsIndexed"] = 4  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        snapshot.profiles[0].label = "replacement"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        snapshot.stale = True  # type: ignore[misc]


def test_to_status_wire_only_overwrites_runtime_fields() -> None:
    status = _full_status(
        connectionState="service-controlled",
        capabilitiesStale="service-stale",
        capabilitiesFetchedAt="service-time",
    )
    snapshot = parse_capability_snapshot(status, fetched_at_ms=1234)

    wire = snapshot.to_status_wire()

    assert wire["connectionState"] == "READY"
    assert wire["capabilitiesStale"] is False
    assert wire["capabilitiesFetchedAt"] == 1234
    for field in (
        "capabilitiesVersion",
        "configuredDefaultRetrievalProfile",
        "effectiveDefaultRetrievalProfile",
        "defaultRetrievalProfile",
        "defaultFallbackReason",
    ):
        assert wire[field] == snapshot.service_status[field]
    assert wire["retrievalProfiles"] is snapshot.service_status["retrievalProfiles"]
    assert snapshot.service_status["connectionState"] == "service-controlled"
    assert snapshot.service_status["capabilitiesStale"] == "service-stale"
    assert snapshot.service_status["capabilitiesFetchedAt"] == "service-time"


def test_legacy_snapshot_does_not_publish_profile_promises() -> None:
    legacy_status = {
        "connectionState": "DEGRADED",
        "fallbackReason": "legacy-search-fallback",
        "defaultRetrievalProfile": "legacy_default",
        "retrievalProfiles": [{"id": "legacy_profile", "available": True}],
        "documentsIndexed": 7,
    }

    snapshot = parse_capability_snapshot(legacy_status, fetched_at_ms=99)

    assert snapshot.state is KnowledgeConnectionState.LEGACY
    assert snapshot.legacy is True
    assert snapshot.capabilities_version is None
    assert snapshot.profiles == ()
    assert snapshot.available_profile_ids == ()
    assert snapshot.configured_default is None
    assert snapshot.effective_default is None
    assert snapshot.fallback_reason is None
    assert snapshot.service_status["connectionState"] == "DEGRADED"
    assert snapshot.service_status["defaultRetrievalProfile"] == "legacy_default"
    wire = snapshot.to_status_wire()
    assert wire["connectionState"] == "LEGACY"
    assert wire["defaultRetrievalProfile"] == "legacy_default"
    assert wire["fallbackReason"] == "legacy-search-fallback"
    assert wire["retrievalProfiles"] == legacy_status["retrievalProfiles"]
    assert wire["documentsIndexed"] == 7


@pytest.mark.parametrize(
    "partial_fields",
    [
        {"capabilitiesVersion": "0123456789abcdef"},
        {"configuredDefaultRetrievalProfile": "sqlite_fts5_default"},
        {"effectiveDefaultRetrievalProfile": "sqlite_fts5_default"},
        {"defaultFallbackReason": "configured_default_unavailable"},
        {
            "capabilitiesVersion": "0123456789abcdef",
            "configuredDefaultRetrievalProfile": "sqlite_fts5_default",
        },
    ],
)
def test_partial_new_contract_is_malformed(partial_fields: dict[str, Any]) -> None:
    status = {
        "defaultRetrievalProfile": "legacy_default",
        "retrievalProfiles": [{"id": "legacy_profile"}],
        **partial_fields,
    }

    _assert_invalid(status)


@pytest.mark.parametrize(
    "version",
    [
        "",
        "0123456789abcde",
        "0123456789abcdef0",
        "0123456789abcdeg",
        "0123456789ABCDEf",
        123,
        None,
    ],
)
def test_capabilities_version_requires_16_lowercase_hex_characters(version: Any) -> None:
    _assert_invalid(_full_status(capabilitiesVersion=version))


@pytest.mark.parametrize(
    "profile_ids",
    [
        ("", "hybrid_rrf_bge_m3_fts5", "vector_unavailable"),
        ("   ", "hybrid_rrf_bge_m3_fts5", "vector_unavailable"),
        ("sqlite_fts5_default", "sqlite_fts5_default", "vector_unavailable"),
    ],
)
def test_profile_ids_must_be_non_empty_and_unique(profile_ids: tuple[str, ...]) -> None:
    status = _full_status()
    profiles = cast(list[dict[str, Any]], status["retrievalProfiles"])
    for profile, profile_id in zip(profiles, profile_ids, strict=True):
        profile["id"] = profile_id

    _assert_invalid(status)


@pytest.mark.parametrize("profiles", [None, {}, (), "profiles"])
def test_retrieval_profiles_must_be_a_list(profiles: Any) -> None:
    _assert_invalid(_full_status(retrievalProfiles=profiles))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", None),
        ("label", None),
        ("label", ""),
        ("kind", None),
        ("kind", ""),
        ("available", 1),
        ("available", "true"),
        ("reason", []),
        ("model", 7),
        ("dimensions", "1024"),
        ("dimensions", True),
    ],
)
def test_retrieval_profile_fields_require_declared_types(field: str, value: Any) -> None:
    status = _full_status()
    profiles = cast(list[dict[str, Any]], status["retrievalProfiles"])
    profiles[0][field] = value

    _assert_invalid(status)


def test_retrieval_profile_entries_must_be_objects() -> None:
    status = _full_status()
    profiles = cast(list[Any], status["retrievalProfiles"])
    profiles[0] = "secret-profile-value"

    _assert_invalid(status)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("configuredDefaultRetrievalProfile", None),
        ("configuredDefaultRetrievalProfile", ""),
        ("effectiveDefaultRetrievalProfile", 3),
        ("effectiveDefaultRetrievalProfile", ""),
        ("defaultFallbackReason", []),
        ("defaultFallbackReason", 1),
        ("defaultFallbackReason", True),
    ],
)
def test_top_level_fields_require_declared_types(field: str, value: Any) -> None:
    _assert_invalid(_full_status(**{field: value}))


def test_default_fallback_reason_is_optional() -> None:
    status = _full_status()
    del status["defaultFallbackReason"]

    snapshot = parse_capability_snapshot(status, fetched_at_ms=1234)

    assert snapshot.state is KnowledgeConnectionState.READY
    assert snapshot.fallback_reason is None
    assert "defaultFallbackReason" not in snapshot.to_status_wire()


def test_default_fallback_reason_may_be_none() -> None:
    snapshot = parse_capability_snapshot(
        _full_status(defaultFallbackReason=None),
        fetched_at_ms=1234,
    )

    assert snapshot.fallback_reason is None


@pytest.mark.parametrize("fetched_at_ms", [None, "1234", True])
def test_fetched_at_requires_an_integer_timestamp(fetched_at_ms: Any) -> None:
    _assert_invalid(FULL_STATUS, fetched_at_ms=fetched_at_ms)


def test_payload_must_be_a_mapping() -> None:
    _assert_invalid(["secret-payload"])


def test_configured_default_must_reference_a_profile() -> None:
    _assert_invalid(
        _full_status(configuredDefaultRetrievalProfile="missing-configured-profile")
    )


def test_effective_default_must_reference_a_profile_when_present() -> None:
    _assert_invalid(_full_status(effectiveDefaultRetrievalProfile="missing-effective-profile"))


def test_effective_default_may_be_none() -> None:
    snapshot = parse_capability_snapshot(
        _full_status(effectiveDefaultRetrievalProfile=None),
        fetched_at_ms=1234,
    )

    assert snapshot.effective_default is None


def test_effective_default_must_reference_an_available_profile() -> None:
    _assert_invalid(_full_status(effectiveDefaultRetrievalProfile="vector_unavailable"))


@pytest.mark.parametrize(
    "status",
    [
        _full_status(capabilitiesVersion="credential-secret"),
        _full_status(configuredDefaultRetrievalProfile="credential-secret"),
        _full_status(effectiveDefaultRetrievalProfile="credential-secret"),
        _full_status(defaultFallbackReason=["credential-secret"]),
        _full_status(retrievalProfiles=["credential-secret"]),
    ],
)
def test_malformed_errors_are_stable_and_do_not_echo_service_values(
    status: dict[str, Any],
) -> None:
    with pytest.raises(ValueError) as raised:
        parse_capability_snapshot(status, fetched_at_ms=1234)

    rendered_error = f"{raised.value!s} {raised.value!r} {raised.value.args!r}"
    assert str(raised.value) == INVALID_SNAPSHOT_MESSAGE
    assert "credential-secret" not in rendered_error
