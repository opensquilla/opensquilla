from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable, Callable
from copy import deepcopy
from dataclasses import FrozenInstanceError
from typing import Any, cast

import pytest

from opensquilla.knowledge.backend import KnowledgeBackendError
from opensquilla.knowledge.runtime import (
    KnowledgeCapabilitySnapshot,
    KnowledgeConnectionState,
    KnowledgeRuntime,
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


class _Clock:
    def __init__(self, *, monotonic: float = 0.0, wall_time_ms: int = 1_000) -> None:
        self.monotonic_value = monotonic
        self.wall_time_ms_value = wall_time_ms

    def monotonic(self) -> float:
        return self.monotonic_value

    def wall_time_ms(self) -> int:
        return self.wall_time_ms_value

    def advance(self, seconds: float) -> None:
        self.monotonic_value += seconds
        self.wall_time_ms_value += int(seconds * 1_000)


class _RecordingBackend:
    def __init__(
        self,
        *responses: dict[str, Any] | BaseException,
        entered: threading.Event | None = None,
        release: threading.Event | None = None,
    ) -> None:
        self._responses = list(responses)
        self._entered = entered
        self._release = release
        self._lock = threading.Lock()
        self.calls = 0

    def status(self) -> dict[str, Any]:
        with self._lock:
            self.calls += 1
            if not self._responses:
                raise AssertionError("unexpected backend status call")
            response = self._responses.pop(0)
        if self._entered is not None:
            self._entered.set()
        if self._release is not None:
            self._release.wait()
        if isinstance(response, BaseException):
            raise response
        return deepcopy(response)


class _ControlledSleeper:
    def __init__(self, *, block_cancellation: bool = False) -> None:
        self.calls: list[float] = []
        self.cancellations = 0
        self.cancellation_started = asyncio.Event()
        self.allow_cancellation = asyncio.Event()
        self._waiters: list[asyncio.Event] = []
        self._changed = asyncio.Event()
        if not block_cancellation:
            self.allow_cancellation.set()

    async def __call__(self, delay: float) -> None:
        waiter = asyncio.Event()
        self.calls.append(delay)
        self._waiters.append(waiter)
        self._changed.set()
        try:
            await waiter.wait()
        except asyncio.CancelledError:
            self.cancellations += 1
            self.cancellation_started.set()
            await self.allow_cancellation.wait()
            raise

    async def wait_for_calls(self, count: int) -> None:
        while len(self.calls) < count:
            self._changed.clear()
            if len(self.calls) >= count:
                return
            await asyncio.wait_for(self._changed.wait(), timeout=1)

    def release(self, index: int) -> None:
        self._waiters[index].set()


def _runtime(
    backend: _RecordingBackend,
    *,
    clock: _Clock | None = None,
    enabled_provider: Callable[[], bool] | None = None,
    ttl_seconds: float = 60.0,
    sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> KnowledgeRuntime:
    runtime_clock = clock or _Clock()
    return KnowledgeRuntime(
        lambda: cast(Any, backend),
        enabled_provider=enabled_provider or (lambda: True),
        ttl_seconds_provider=lambda: ttl_seconds,
        monotonic=runtime_clock.monotonic,
        wall_time_ms=runtime_clock.wall_time_ms,
        sleeper=sleeper,
    )


def _capability_error(code: str) -> KnowledgeBackendError:
    return KnowledgeBackendError(status_code=409, code=code, message="safe failure")


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


@pytest.mark.asyncio
async def test_disabled_start_stays_disconnected_without_backend_call() -> None:
    sleeper = _ControlledSleeper()
    backend = _RecordingBackend(FULL_STATUS)
    runtime = _runtime(
        backend,
        enabled_provider=lambda: False,
        sleeper=sleeper,
    )

    await runtime.start()
    await sleeper.wait_for_calls(1)

    assert runtime.snapshot() is None
    assert runtime.status_payload()["connectionState"] == "DISCONNECTED"
    assert backend.calls == 0
    await runtime.stop()


@pytest.mark.asyncio
async def test_start_returns_before_slow_refresh_and_transitions_to_ready() -> None:
    entered = threading.Event()
    release = threading.Event()
    sleeper = _ControlledSleeper()
    backend = _RecordingBackend(FULL_STATUS, entered=entered, release=release)
    runtime = _runtime(backend, sleeper=sleeper)

    try:
        await asyncio.wait_for(runtime.start(), timeout=1)

        assert runtime.status_payload()["connectionState"] == "DISCOVERING"
        assert runtime.snapshot() is None
        await asyncio.wait_for(asyncio.to_thread(entered.wait), timeout=1)
    finally:
        release.set()
    snapshot = await runtime.refresh()
    await sleeper.wait_for_calls(1)

    assert snapshot is not None
    assert snapshot.state is KnowledgeConnectionState.READY
    assert runtime.status_payload()["connectionState"] == "READY"
    await runtime.stop()


@pytest.mark.asyncio
async def test_refresh_uses_ready_snapshot_until_ttl_expires() -> None:
    clock = _Clock()
    backend = _RecordingBackend(FULL_STATUS, FULL_STATUS)
    runtime = _runtime(backend, clock=clock, ttl_seconds=60)

    first = await runtime.refresh()
    clock.advance(59)
    cached = await runtime.refresh()

    assert cached is first
    assert backend.calls == 1

    clock.advance(2)
    refreshed = await runtime.refresh()

    assert refreshed is not first
    assert backend.calls == 2
    assert refreshed is not None
    assert refreshed.fetched_at_ms == 62_000


@pytest.mark.asyncio
async def test_force_refresh_singleflight_shares_one_unlocked_backend_request() -> None:
    entered = threading.Event()
    release = threading.Event()
    backend = _RecordingBackend(FULL_STATUS, entered=entered, release=release)
    runtime = _runtime(backend)
    start = asyncio.Event()
    all_ready = asyncio.Event()
    ready_count = 0

    async def force_refresh() -> KnowledgeCapabilitySnapshot | None:
        nonlocal ready_count
        ready_count += 1
        if ready_count == 20:
            all_ready.set()
        await start.wait()
        return await runtime.refresh(force=True)

    refreshes = [asyncio.create_task(force_refresh()) for _ in range(20)]
    try:
        await asyncio.wait_for(all_ready.wait(), timeout=1)
        start.set()
        await asyncio.wait_for(asyncio.to_thread(entered.wait), timeout=1)
        assert backend.calls == 1
    finally:
        release.set()

    snapshots = await asyncio.gather(*refreshes)

    assert backend.calls == 1
    assert all(snapshot is snapshots[0] for snapshot in snapshots)


@pytest.mark.asyncio
async def test_cancelling_one_refresh_waiter_does_not_cancel_shared_request() -> None:
    entered = threading.Event()
    release = threading.Event()
    backend = _RecordingBackend(FULL_STATUS, entered=entered, release=release)
    runtime = _runtime(backend)
    start = asyncio.Event()
    all_ready = asyncio.Event()
    ready_count = 0

    async def refresh_waiter() -> KnowledgeCapabilitySnapshot | None:
        nonlocal ready_count
        ready_count += 1
        if ready_count == 2:
            all_ready.set()
        await start.wait()
        return await runtime.refresh(force=True)

    cancelled_waiter = asyncio.create_task(refresh_waiter())
    successful_waiter = asyncio.create_task(refresh_waiter())
    try:
        await asyncio.wait_for(all_ready.wait(), timeout=1)
        start.set()
        await asyncio.wait_for(asyncio.to_thread(entered.wait), timeout=1)
        next_turn = asyncio.Event()
        asyncio.get_running_loop().call_soon(next_turn.set)
        await next_turn.wait()

        cancelled_waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cancelled_waiter
        assert successful_waiter.done() is False
        assert backend.calls == 1
    finally:
        release.set()

    snapshot = await successful_waiter
    assert snapshot is not None
    assert snapshot.state is KnowledgeConnectionState.READY
    assert backend.calls == 1


@pytest.mark.asyncio
async def test_failed_refresh_degrades_then_recovers_without_changing_fetch_time() -> None:
    clock = _Clock()
    backend = _RecordingBackend(
        FULL_STATUS,
        RuntimeError("credential-secret"),
        FULL_STATUS,
    )
    runtime = _runtime(backend, clock=clock)
    ready = await runtime.refresh()
    assert ready is not None
    clock.advance(5)

    stale = await runtime.refresh(force=True)

    assert stale is not None
    assert stale is runtime.snapshot()
    assert stale is not ready
    assert stale.state is KnowledgeConnectionState.DEGRADED
    assert stale.stale is True
    assert stale.fetched_at_ms == ready.fetched_at_ms
    assert runtime.status_payload()["connectionState"] == "DEGRADED"
    assert runtime.status_payload()["capabilitiesStale"] is True

    recovered = await runtime.refresh()

    assert recovered is not None
    assert recovered.state is KnowledgeConnectionState.READY
    assert recovered.stale is False


@pytest.mark.asyncio
async def test_initial_refresh_failure_becomes_unavailable_without_snapshot() -> None:
    backend = _RecordingBackend(RuntimeError("credential-secret"))
    runtime = _runtime(backend)

    result = await runtime.refresh()

    assert result is None
    assert runtime.snapshot() is None
    assert runtime.status_payload() == {
        "connectionState": "UNAVAILABLE",
        "capabilitiesStale": False,
        "capabilitiesFetchedAt": None,
    }


@pytest.mark.asyncio
async def test_start_refresh_failure_transitions_discovering_to_unavailable() -> None:
    entered = threading.Event()
    release = threading.Event()
    sleeper = _ControlledSleeper()
    backend = _RecordingBackend(
        RuntimeError("credential-secret"),
        entered=entered,
        release=release,
    )
    runtime = _runtime(backend, sleeper=sleeper)

    await runtime.start()
    assert runtime.status_payload()["connectionState"] == "DISCOVERING"
    await asyncio.wait_for(asyncio.to_thread(entered.wait), timeout=1)
    release.set()
    await sleeper.wait_for_calls(1)

    assert runtime.snapshot() is None
    assert runtime.status_payload()["connectionState"] == "UNAVAILABLE"
    await runtime.stop()


@pytest.mark.asyncio
async def test_refresh_accepts_legacy_protocol_payload() -> None:
    backend = _RecordingBackend({"documentsIndexed": 7, "ok": True})
    runtime = _runtime(backend)

    snapshot = await runtime.refresh()

    assert snapshot is not None
    assert snapshot.state is KnowledgeConnectionState.LEGACY
    assert snapshot.legacy is True
    assert runtime.status_payload()["connectionState"] == "LEGACY"


@pytest.mark.asyncio
async def test_disabled_refresh_clears_ready_snapshot_without_backend_call() -> None:
    enabled = True
    backend = _RecordingBackend(FULL_STATUS)
    runtime = _runtime(backend, enabled_provider=lambda: enabled)
    assert await runtime.refresh() is not None
    assert backend.calls == 1
    enabled = False

    result = await runtime.refresh(force=True)

    assert result is None
    assert runtime.snapshot() is None
    assert runtime.status_payload()["connectionState"] == "DISCONNECTED"
    assert backend.calls == 1


@pytest.mark.asyncio
async def test_disable_during_failed_refresh_finishes_disconnected() -> None:
    enabled = True
    entered = threading.Event()
    release = threading.Event()
    backend = _RecordingBackend(
        RuntimeError("credential-secret"),
        entered=entered,
        release=release,
    )
    runtime = _runtime(backend, enabled_provider=lambda: enabled)

    refresh = asyncio.create_task(runtime.refresh(force=True))
    await asyncio.wait_for(asyncio.to_thread(entered.wait), timeout=1)
    enabled = False
    release.set()

    assert await refresh is None
    assert runtime.snapshot() is None
    assert runtime.status_payload()["connectionState"] == "DISCONNECTED"


@pytest.mark.asyncio
async def test_invalidate_during_refresh_is_not_lost_by_success() -> None:
    entered = threading.Event()
    release = threading.Event()
    backend = _RecordingBackend(
        FULL_STATUS,
        FULL_STATUS,
        entered=entered,
        release=release,
    )
    runtime = _runtime(backend, ttl_seconds=3_600)

    refresh = asyncio.create_task(runtime.refresh())
    await asyncio.wait_for(asyncio.to_thread(entered.wait), timeout=1)
    runtime.invalidate("settings_updated")
    release.set()
    first = await refresh
    assert first is not None
    entered.clear()
    release.clear()

    second_refresh = asyncio.create_task(runtime.refresh())
    await asyncio.wait_for(asyncio.to_thread(entered.wait), timeout=1)
    release.set()
    second = await second_refresh

    assert second is not first
    assert backend.calls == 2


@pytest.mark.asyncio
async def test_invalidate_settings_updated_bypasses_refresh_ttl() -> None:
    backend = _RecordingBackend(FULL_STATUS, FULL_STATUS)
    runtime = _runtime(backend, ttl_seconds=3_600)
    first = await runtime.refresh()

    runtime.invalidate("settings_updated")
    second = await runtime.refresh()

    assert second is not first
    assert backend.calls == 2


@pytest.mark.parametrize(
    "code",
    [
        "invalid_retrieval_profile",
        "retrieval_profile_unavailable",
        "no_retrieval_profile_available",
    ],
)
@pytest.mark.asyncio
async def test_capability_failure_forces_refresh_and_retries_once(code: str) -> None:
    backend = _RecordingBackend(FULL_STATUS)
    runtime = _runtime(backend)
    attempts = 0

    def operation(_backend: Any) -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise _capability_error(code)
        return "retried"

    result = await runtime.call_with_capability_retry(operation)

    assert result == "retried"
    assert attempts == 2
    assert backend.calls == 1


@pytest.mark.asyncio
async def test_second_capability_failure_is_returned_without_another_retry() -> None:
    backend = _RecordingBackend(FULL_STATUS)
    runtime = _runtime(backend)
    attempts = 0
    error = _capability_error("invalid_retrieval_profile")

    def operation(_backend: Any) -> None:
        nonlocal attempts
        attempts += 1
        raise error

    with pytest.raises(KnowledgeBackendError) as raised:
        await runtime.call_with_capability_retry(operation)

    assert raised.value is error
    assert attempts == 2
    assert backend.calls == 1


@pytest.mark.asyncio
async def test_non_capability_failure_is_returned_without_refresh_or_retry() -> None:
    backend = _RecordingBackend()
    runtime = _runtime(backend)
    attempts = 0
    error = _capability_error("settings_persist_failed")

    def operation(_backend: Any) -> None:
        nonlocal attempts
        attempts += 1
        raise error

    with pytest.raises(KnowledgeBackendError) as raised:
        await runtime.call_with_capability_retry(operation)

    assert raised.value is error
    assert attempts == 1
    assert backend.calls == 0


@pytest.mark.asyncio
async def test_background_retry_delays_are_exact_and_capped() -> None:
    sleeper = _ControlledSleeper()
    backend = _RecordingBackend(*(RuntimeError("service unavailable") for _ in range(6)))
    runtime = _runtime(backend, sleeper=sleeper)

    await runtime.start()
    expected_delays = [1, 2, 5, 10, 30, 30]
    for index, expected in enumerate(expected_delays):
        await sleeper.wait_for_calls(index + 1)
        assert sleeper.calls[index] == expected
        if index + 1 < len(expected_delays):
            sleeper.release(index)

    assert backend.calls == 6
    await runtime.stop()


@pytest.mark.asyncio
async def test_background_waits_only_until_latest_refresh_ttl_deadline() -> None:
    clock = _Clock()
    sleeper = _ControlledSleeper()
    backend = _RecordingBackend(FULL_STATUS, FULL_STATUS)
    runtime = _runtime(backend, clock=clock, ttl_seconds=60, sleeper=sleeper)
    await runtime.start()
    await sleeper.wait_for_calls(1)
    assert sleeper.calls == [60]

    clock.advance(1)
    forced = await runtime.refresh(force=True)
    assert forced is not None
    assert backend.calls == 2

    clock.advance(59)
    sleeper.release(0)
    await sleeper.wait_for_calls(2)

    assert backend.calls == 2
    assert sleeper.calls == [60, 1]
    await runtime.stop()


@pytest.mark.parametrize(
    "invalid_ttl",
    [
        pytest.param(0.0, id="zero"),
        pytest.param(-1.0, id="negative"),
        pytest.param(float("nan"), id="nan"),
        pytest.param(float("inf"), id="positive_infinity"),
        pytest.param(float("-inf"), id="negative_infinity"),
    ],
)
@pytest.mark.asyncio
async def test_invalid_ttl_uses_safe_retry_without_backend_calls(
    invalid_ttl: float,
) -> None:
    sleeper = _ControlledSleeper()
    backend = _RecordingBackend(FULL_STATUS, FULL_STATUS, FULL_STATUS)
    runtime = _runtime(backend, ttl_seconds=invalid_ttl, sleeper=sleeper)

    with pytest.raises(ValueError) as raised:
        await runtime.refresh(raise_on_error=True)

    assert str(raised.value) == "invalid knowledge capability TTL"
    assert raised.value.args == ("invalid knowledge capability TTL",)
    assert repr(invalid_ttl) not in str(raised.value)
    assert backend.calls == 0
    assert runtime.status_payload()["connectionState"] == "UNAVAILABLE"

    await runtime.start()
    await sleeper.wait_for_calls(1)
    assert sleeper.calls == [1]
    assert backend.calls == 0

    sleeper.release(0)
    await sleeper.wait_for_calls(2)
    assert sleeper.calls == [1, 2]
    assert backend.calls == 0
    await runtime.stop()


@pytest.mark.asyncio
async def test_request_refresh_returns_immediately_and_wakes_background_loop() -> None:
    sleeper = _ControlledSleeper()
    entered = threading.Event()
    backend = _RecordingBackend(FULL_STATUS, FULL_STATUS, entered=entered)
    runtime = _runtime(backend, sleeper=sleeper)
    await runtime.start()
    await sleeper.wait_for_calls(1)
    assert backend.calls == 1
    entered.clear()

    runtime.request_refresh()

    await asyncio.wait_for(asyncio.to_thread(entered.wait), timeout=1)
    assert backend.calls == 2
    await runtime.stop()


@pytest.mark.asyncio
async def test_stop_cancels_and_awaits_background_sleeper_and_is_idempotent() -> None:
    sleeper = _ControlledSleeper()
    backend = _RecordingBackend(FULL_STATUS)
    runtime = _runtime(backend, sleeper=sleeper)
    await runtime.start()
    await sleeper.wait_for_calls(1)

    await runtime.stop()

    assert sleeper.cancellations == 1
    await runtime.stop()
    assert sleeper.cancellations == 1


@pytest.mark.asyncio
async def test_concurrent_start_waits_for_stop_to_finish_old_background() -> None:
    sleeper = _ControlledSleeper(block_cancellation=True)
    backend = _RecordingBackend(FULL_STATUS)
    runtime = _runtime(backend, sleeper=sleeper)
    await runtime.start()
    await sleeper.wait_for_calls(1)

    stop_task = asyncio.create_task(runtime.stop())
    await asyncio.wait_for(sleeper.cancellation_started.wait(), timeout=1)
    start_task = asyncio.create_task(runtime.start())
    next_turn = asyncio.Event()
    asyncio.get_running_loop().call_soon(next_turn.set)
    await next_turn.wait()

    try:
        assert start_task.done() is False
        assert sleeper.calls == [60]
    finally:
        sleeper.allow_cancellation.set()
        await stop_task
        await start_task

    await sleeper.wait_for_calls(2)
    assert sleeper.calls == [60, 60]
    await runtime.stop()
    assert sleeper.cancellations == 2


@pytest.mark.asyncio
async def test_refresh_raise_on_error_updates_state_before_returning_error() -> None:
    error = RuntimeError("credential-secret")
    backend = _RecordingBackend(error)
    runtime = _runtime(backend)

    with pytest.raises(RuntimeError) as raised:
        await runtime.refresh(raise_on_error=True)

    assert raised.value is error
    assert runtime.snapshot() is None
    assert runtime.status_payload()["connectionState"] == "UNAVAILABLE"


def test_current_backend_resolves_provider_each_time() -> None:
    first = _RecordingBackend(FULL_STATUS)
    second = _RecordingBackend(FULL_STATUS)
    selected = first
    runtime = KnowledgeRuntime(
        lambda: cast(Any, selected),
        enabled_provider=lambda: True,
        ttl_seconds_provider=lambda: 60,
    )

    assert runtime.current_backend() is first
    selected = second
    assert runtime.current_backend() is second


@pytest.mark.asyncio
async def test_refresh_failure_logs_do_not_disclose_backend_message(caplog: Any) -> None:
    backend = _RecordingBackend(RuntimeError("credential-secret"))
    runtime = _runtime(backend)

    await runtime.refresh()

    assert "credential-secret" not in caplog.text
