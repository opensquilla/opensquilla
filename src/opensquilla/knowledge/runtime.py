from __future__ import annotations

import asyncio
import logging
import math
import re
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from types import MappingProxyType
from typing import Any, TypeVar

from opensquilla.knowledge.backend import KnowledgeBackend, KnowledgeBackendError

_INVALID_SNAPSHOT_MESSAGE = "invalid knowledge capability snapshot"
_INVALID_TTL_MESSAGE = "invalid knowledge capability TTL"
_CAPABILITIES_VERSION = re.compile("[0-9a-f]{16}")
_LOGGER = logging.getLogger(__name__)
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
_CAPABILITY_ERROR_CODES = frozenset(
    {
        "invalid_retrieval_profile",
        "retrieval_profile_unavailable",
        "no_retrieval_profile_available",
    }
)
_RETRY_DELAYS_SECONDS = (1.0, 2.0, 5.0, 10.0, 30.0)
_ResultT = TypeVar("_ResultT")


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


class KnowledgeRuntime:
    def __init__(
        self,
        backend_provider: Callable[[], KnowledgeBackend],
        *,
        enabled_provider: Callable[[], bool],
        ttl_seconds_provider: Callable[[], float],
        monotonic: Callable[[], float] = time.monotonic,
        wall_time_ms: Callable[[], int] = lambda: int(time.time() * 1000),
        sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._backend_provider = backend_provider
        self._enabled_provider = enabled_provider
        self._ttl_seconds_provider = ttl_seconds_provider
        self._monotonic = monotonic
        self._wall_time_ms = wall_time_ms
        self._sleeper = sleeper
        self._lock = asyncio.Lock()
        self._lifecycle_lock = asyncio.Lock()
        self._refresh_requested = asyncio.Event()
        self._background_task: asyncio.Task[None] | None = None
        self._refresh_task: asyncio.Task[KnowledgeCapabilitySnapshot | None] | None = (
            None
        )
        self._snapshot: KnowledgeCapabilitySnapshot | None = None
        self._state = KnowledgeConnectionState.DISCONNECTED
        self._last_success_monotonic: float | None = None
        self._invalidation_generation = 1
        self._validated_generation = 0

    def current_backend(self) -> KnowledgeBackend:
        return self._backend_provider()

    def snapshot(self) -> KnowledgeCapabilitySnapshot | None:
        return self._snapshot

    def status_payload(self) -> dict[str, Any]:
        snapshot = self._snapshot
        if snapshot is not None:
            return snapshot.to_status_wire()
        return {
            "connectionState": self._state.value,
            "capabilitiesStale": False,
            "capabilitiesFetchedAt": None,
        }

    async def start(self) -> None:
        async with self._lifecycle_lock:
            await self._start()

    async def _start(self) -> None:
        async with self._lock:
            if self._background_task is not None and not self._background_task.done():
                return
            if self._enabled_provider():
                if self._snapshot is None:
                    self._state = KnowledgeConnectionState.DISCOVERING
            else:
                self._disconnect()
            self._background_task = asyncio.create_task(
                self._background_loop(),
                name="knowledge-capability-refresh",
            )

    async def stop(self) -> None:
        async with self._lifecycle_lock:
            await self._stop()

    async def _stop(self) -> None:
        async with self._lock:
            background_task = self._background_task
            refresh_task = self._refresh_task
            self._background_task = None

        tasks = {
            task
            for task in (background_task, refresh_task)
            if task is not None and not task.done()
        }
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        async with self._lock:
            if self._refresh_task is refresh_task:
                self._refresh_task = None
            self._refresh_requested.clear()

    def invalidate(self, _reason: str) -> None:
        self._invalidation_generation += 1

    def request_refresh(self) -> None:
        self._refresh_requested.set()

    async def call_with_capability_retry(
        self,
        operation: Callable[[KnowledgeBackend], _ResultT],
    ) -> _ResultT:
        try:
            return await asyncio.to_thread(operation, self.current_backend())
        except KnowledgeBackendError as error:
            if error.code not in _CAPABILITY_ERROR_CODES:
                raise

        await self.refresh(force=True)
        return await asyncio.to_thread(operation, self.current_backend())

    async def refresh(
        self,
        *,
        force: bool = False,
        raise_on_error: bool = False,
    ) -> KnowledgeCapabilitySnapshot | None:
        async with self._lock:
            task = self._refresh_task
            if task is None or task.done():
                task = asyncio.create_task(self._refresh_once(force=force))
                self._refresh_task = task

        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            raise
        except Exception:
            if raise_on_error:
                raise
            return self._snapshot
        finally:
            if task.done():
                async with self._lock:
                    if self._refresh_task is task:
                        self._refresh_task = None

    async def _refresh_once(
        self,
        *,
        force: bool,
    ) -> KnowledgeCapabilitySnapshot | None:
        if not self._enabled_provider():
            async with self._lock:
                self._disconnect()
            return None

        started = self._monotonic()
        try:
            async with self._lock:
                if self._snapshot is None:
                    self._state = KnowledgeConnectionState.DISCOVERING
                now = self._monotonic()
                ttl_seconds = self._ttl_seconds()
                if self._can_use_cached_snapshot(
                    now=now,
                    ttl_seconds=ttl_seconds,
                    force=force,
                ):
                    return self._snapshot
                generation = self._invalidation_generation

            backend = self.current_backend()
            payload = await asyncio.to_thread(backend.status)
            refreshed = parse_capability_snapshot(
                payload,
                fetched_at_ms=self._wall_time_ms(),
            )
        except Exception as error:
            still_enabled = self._enabled_provider()
            async with self._lock:
                if not still_enabled:
                    self._disconnect()
                elif self._snapshot is None:
                    self._state = KnowledgeConnectionState.UNAVAILABLE
                else:
                    self._snapshot = replace(
                        self._snapshot,
                        state=KnowledgeConnectionState.DEGRADED,
                        stale=True,
                    )
                    self._state = KnowledgeConnectionState.DEGRADED
                state = self._state
            _LOGGER.warning(
                "knowledge capability refresh failed state=%s reason=%s duration_ms=%d",
                state.value,
                _error_category(error),
                max(0, int((self._monotonic() - started) * 1_000)),
            )
            raise

        still_enabled = self._enabled_provider()
        async with self._lock:
            if not still_enabled:
                self._disconnect()
                return None
            self._snapshot = refreshed
            self._state = refreshed.state
            self._last_success_monotonic = self._monotonic()
            self._validated_generation = generation

        _LOGGER.info(
            "knowledge capability refresh succeeded state=%s version=%s duration_ms=%d",
            refreshed.state.value,
            refreshed.capabilities_version,
            max(0, int((self._monotonic() - started) * 1_000)),
        )
        return refreshed

    def _can_use_cached_snapshot(
        self,
        *,
        now: float,
        ttl_seconds: float,
        force: bool,
    ) -> bool:
        return (
            not force
            and self._snapshot is not None
            and self._state
            in {KnowledgeConnectionState.READY, KnowledgeConnectionState.LEGACY}
            and self._last_success_monotonic is not None
            and self._validated_generation == self._invalidation_generation
            and now - self._last_success_monotonic < ttl_seconds
        )

    def _disconnect(self) -> None:
        self._snapshot = None
        self._state = KnowledgeConnectionState.DISCONNECTED
        self._last_success_monotonic = None

    async def _background_loop(self) -> None:
        retry_index = 0
        force = False
        while True:
            snapshot = await self.refresh(force=force)
            force = False
            if not self._enabled_provider():
                delay, retry_index = self._ttl_or_retry_delay()
            elif snapshot is None or snapshot.stale:
                delay, retry_index = self._retry_delay(retry_index)
            else:
                delay, retry_index = self._ttl_or_retry_delay()
            force = await self._wait_for_refresh(delay)

    def _ttl_or_retry_delay(self) -> tuple[float, int]:
        try:
            return self._remaining_ttl_delay(), 0
        except ValueError:
            return self._retry_delay(0)

    @staticmethod
    def _retry_delay(retry_index: int) -> tuple[float, int]:
        delay = _RETRY_DELAYS_SECONDS[retry_index]
        next_index = min(retry_index + 1, len(_RETRY_DELAYS_SECONDS) - 1)
        return delay, next_index

    def _remaining_ttl_delay(self) -> float:
        ttl_seconds = self._ttl_seconds()
        if self._last_success_monotonic is None:
            return ttl_seconds
        elapsed = max(0.0, self._monotonic() - self._last_success_monotonic)
        return max(0.0, ttl_seconds - elapsed)

    def _ttl_seconds(self) -> float:
        try:
            ttl_seconds = float(self._ttl_seconds_provider())
        except (TypeError, ValueError, OverflowError):
            raise ValueError(_INVALID_TTL_MESSAGE) from None
        if ttl_seconds <= 0.0 or not math.isfinite(ttl_seconds):
            raise ValueError(_INVALID_TTL_MESSAGE)
        return ttl_seconds

    async def _wait_for_refresh(self, delay: float) -> bool:
        event_task = asyncio.create_task(self._refresh_requested.wait())
        sleep_task: asyncio.Future[None] = asyncio.ensure_future(self._sleeper(delay))
        tasks: set[asyncio.Future[Any]] = {event_task, sleep_task}
        try:
            done, _pending = await asyncio.wait(
                tasks,
                return_when=asyncio.FIRST_COMPLETED,
            )
            requested = event_task in done or self._refresh_requested.is_set()
            if requested:
                self._refresh_requested.clear()
            return requested
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


def _error_category(error: Exception) -> str:
    if isinstance(error, ValueError) and str(error) == _INVALID_TTL_MESSAGE:
        return "invalid_ttl"
    if isinstance(error, ValueError):
        return "invalid_snapshot"
    return "backend_unavailable"
