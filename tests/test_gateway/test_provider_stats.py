"""Unit tests for the rolling provider-call stats store (offline, injected clock)."""

from __future__ import annotations

from opensquilla.gateway.boot import build_provider_call_observer
from opensquilla.gateway.provider_stats import ProviderStatsStore


class _Clock:
    def __init__(self, start: float = 1_000_000.0) -> None:
        self.value = start

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def _fill(
    store: ProviderStatsStore,
    *,
    provider_id: str = "openrouter",
    count: int = 5,
    ttft_ms: int | None = 120,
) -> None:
    for _ in range(count):
        store.record(
            provider_id=provider_id,
            model="openai/gpt-5.1",
            ttft_ms=ttft_ms,
            duration_ms=900,
            ok=True,
        )


def test_snapshot_none_for_unknown_provider() -> None:
    store = ProviderStatsStore(now=_Clock())
    assert store.snapshot("openrouter") is None


def test_snapshot_none_below_min_samples() -> None:
    store = ProviderStatsStore(now=_Clock())
    _fill(store, count=4)
    assert store.snapshot("openrouter") is None


def test_snapshot_reports_p50_and_gates_p95_below_ten_samples() -> None:
    store = ProviderStatsStore(now=_Clock())
    _fill(store, count=5, ttft_ms=100)

    snap = store.snapshot("openrouter")
    assert snap == {
        "p50TtftMs": 100,
        "p95TtftMs": None,
        "samples": 5,
        "windowMinutes": 60,
    }


def test_snapshot_reports_p95_at_ten_samples() -> None:
    store = ProviderStatsStore(now=_Clock())
    for ttft in (10, 20, 30, 40, 50, 60, 70, 80, 90, 1000):
        store.record(
            provider_id="openrouter",
            model="m",
            ttft_ms=ttft,
            duration_ms=100,
            ok=True,
        )

    snap = store.snapshot("openrouter")
    assert snap is not None
    assert snap["samples"] == 10
    assert snap["p50TtftMs"] == 50
    assert snap["p95TtftMs"] == 1000


def test_snapshot_p95_gates_on_ttft_carrying_samples_not_window_size() -> None:
    store = ProviderStatsStore(now=_Clock())
    # 9 failed calls without a TTFT plus one success: the window holds 10
    # samples, but a single TTFT must not become a p95 readout.
    _fill(store, count=9, ttft_ms=None)
    _fill(store, count=1, ttft_ms=5000)

    snap = store.snapshot("openrouter")
    assert snap is not None
    assert snap["samples"] == 10
    assert snap["p50TtftMs"] == 5000
    assert snap["p95TtftMs"] is None


def test_snapshot_windowing_drops_old_samples() -> None:
    clock = _Clock()
    store = ProviderStatsStore(now=clock)
    _fill(store, count=3, ttft_ms=50)
    clock.advance(3601.0)
    _fill(store, count=3, ttft_ms=200)

    # Only the 3 recent samples are in the window — below the minimum.
    assert store.snapshot("openrouter") is None

    _fill(store, count=2, ttft_ms=200)
    snap = store.snapshot("openrouter")
    assert snap is not None
    assert snap["samples"] == 5
    assert snap["p50TtftMs"] == 200


def test_snapshot_ttft_percentiles_skip_none_ttft_entries() -> None:
    store = ProviderStatsStore(now=_Clock())
    _fill(store, count=4, ttft_ms=None)
    _fill(store, count=2, ttft_ms=300)

    snap = store.snapshot("openrouter")
    assert snap is not None
    assert snap["samples"] == 6
    assert snap["p50TtftMs"] == 300
    assert snap["p95TtftMs"] is None


def test_snapshot_all_none_ttft_yields_none_percentiles() -> None:
    store = ProviderStatsStore(now=_Clock())
    _fill(store, count=12, ttft_ms=None)

    snap = store.snapshot("openrouter")
    assert snap is not None
    assert snap["samples"] == 12
    assert snap["p50TtftMs"] is None
    assert snap["p95TtftMs"] is None


def test_record_ignores_empty_provider_id() -> None:
    store = ProviderStatsStore(now=_Clock())
    _fill(store, provider_id="", count=10)
    assert store.snapshot("") is None


def test_record_bounds_samples_per_provider() -> None:
    store = ProviderStatsStore(now=_Clock())
    _fill(store, count=500, ttft_ms=10)

    snap = store.snapshot("openrouter")
    assert snap is not None
    assert snap["samples"] == 200


def test_boot_observer_adapter_records_into_store() -> None:
    store = ProviderStatsStore(now=_Clock())
    observer = build_provider_call_observer(store)
    assert observer is not None

    for _ in range(5):
        observer(
            provider_id="openrouter",
            model="openai/gpt-5.1",
            ttft_ms=80,
            duration_ms=500,
            ok=True,
            failure_kind="",
        )

    snap = store.snapshot("openrouter")
    assert snap is not None
    assert snap["p50TtftMs"] == 80
    assert snap["samples"] == 5


def test_boot_observer_adapter_is_none_without_store() -> None:
    assert build_provider_call_observer(None) is None
