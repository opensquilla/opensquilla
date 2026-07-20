from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from opensquilla.engine.usage_accounting import (
    UsageAccountingUnavailableError,
    UsageCallItem,
    UsageCallResult,
    UsageCallStart,
)
from opensquilla.gateway.boot import _auto_propose_usage_execution_context
from opensquilla.gateway.usage_ledger_runtime import (
    SessionUsageEventSink,
    UsageLedgerStorageError,
)


def _call(**overrides) -> UsageCallStart:
    values = {
        "event_id": "event-1",
        "execution_id": "turn-1",
        "call_index": 1,
        "agent_run_id": "run-1",
        "turn_id": "turn-1",
        "parent_turn_id": None,
        "session_id": "session-1",
        "session_epoch": 3,
        "agent_id": "main",
        "run_kind": "agent",
        "provider": "provider-a",
        "model": "model-a",
        "started_at_ms": 1_000,
    }
    values.update(overrides)
    return UsageCallStart(**values)


def _result(*, source: str = "mixed") -> UsageCallResult:
    return UsageCallResult(
        completed_at_ms=2_000,
        input_tokens=11,
        output_tokens=7,
        reasoning_tokens=3,
        cache_read_tokens=2,
        cache_write_tokens=1,
        billed_cost_nanos=4,
        estimated_cost_nanos=5,
        cost_source=source,
        estimate_basis="cache_aware",
        price_source="catalog",
        items=(
            UsageCallItem(
                ordinal=0,
                provider="provider-a",
                model="model-a",
                input_tokens=11,
                output_tokens=7,
                reasoning_tokens=3,
                cache_read_tokens=2,
                cache_write_tokens=1,
                billed_cost_nanos=4,
                estimated_cost_nanos=5,
                cost_source=source,
                estimate_basis="cache_aware",
                price_source="catalog",
            ),
        ),
    )


def test_auto_propose_uses_stable_synthetic_session_and_unique_runs() -> None:
    sink = object()
    first = _auto_propose_usage_execution_context("main", sink)
    second = _auto_propose_usage_execution_context("main", sink)

    assert first is not None and second is not None
    assert first.execution_id != second.execution_id
    assert first.session_id == second.session_id
    assert first.run_kind == second.run_kind == "auto_propose"
    assert _auto_propose_usage_execution_context("main", None) is None


class _Storage:
    def __init__(self) -> None:
        self.started = []
        self.finalized = []
        self.unknown = []
        self.fail_finalize = 0

    async def start_usage_event(self, event):
        self.started.append(event)

    async def finalize_usage_event(self, event_id, completion, *, items=()):
        if self.fail_finalize:
            self.fail_finalize -= 1
            raise RuntimeError("busy")
        self.finalized.append((event_id, completion, tuple(items)))

    async def mark_usage_event_unknown(self, event_id, *, completed_at_ms, reason=None):
        self.unknown.append((event_id, completed_at_ms, reason))


@pytest.mark.asyncio
async def test_start_persists_identity_before_provider_dispatch() -> None:
    storage = _Storage()
    sink = SessionUsageEventSink(storage)

    await sink.start(_call())

    event = storage.started[0]
    assert event.event_id == "event-1"
    assert event.execution_id == "turn-1"
    assert event.session_id == "session-1"
    assert event.origin == "live_provider"


@pytest.mark.asyncio
async def test_start_without_durable_session_fails_closed() -> None:
    storage = _Storage()
    sink = SessionUsageEventSink(storage)

    with pytest.raises(UsageLedgerStorageError, match="durable session identity"):
        await sink.start(replace(_call(), session_id=None))

    assert storage.started == []
    assert issubclass(UsageLedgerStorageError, UsageAccountingUnavailableError)


@pytest.mark.asyncio
async def test_finalize_writes_envelope_and_items_without_double_counting() -> None:
    storage = _Storage()
    sink = SessionUsageEventSink(storage)

    await sink.finalize(_call(), _result())

    event_id, completion, items = storage.finalized[0]
    assert event_id == "event-1"
    assert completion.total_tokens == 18
    assert completion.cost_nanos == 9
    assert completion.cost_nanos == (
        completion.billed_cost_nanos + completion.estimated_cost_nanos
    )
    assert sum(item.cost_nanos for item in items) == completion.cost_nanos


@pytest.mark.asyncio
async def test_finalize_marks_partial_member_receipt_coverage() -> None:
    storage = _Storage()
    sink = SessionUsageEventSink(storage)

    await sink.finalize(_call(), replace(_result(), missing_usage_entries=2))

    _, completion, items = storage.finalized[0]
    assert completion.coverage_status == "usage_missing"
    assert completion.missing_cost_entries == 2
    assert completion.cost_nanos == sum(item.cost_nanos for item in items)


@pytest.mark.asyncio
async def test_priced_ensemble_member_does_not_hide_unpriced_sibling() -> None:
    storage = _Storage()
    sink = SessionUsageEventSink(storage)
    priced = UsageCallItem(
        ordinal=0,
        provider="provider-a",
        model="model-a",
        input_tokens=5,
        output_tokens=0,
        reasoning_tokens=0,
        cache_read_tokens=0,
        cache_write_tokens=0,
        billed_cost_nanos=4,
        estimated_cost_nanos=0,
        cost_source="provider_billed",
        estimate_basis=None,
        price_source=None,
    )
    unpriced = UsageCallItem(
        ordinal=1,
        provider="provider-b",
        model="model-b",
        input_tokens=6,
        output_tokens=7,
        reasoning_tokens=3,
        cache_read_tokens=2,
        cache_write_tokens=1,
        billed_cost_nanos=0,
        estimated_cost_nanos=0,
        cost_source="unavailable",
        estimate_basis=None,
        price_source=None,
    )
    result = replace(
        _result(),
        billed_cost_nanos=4,
        estimated_cost_nanos=0,
        cost_source="provider_billed",
        items=(priced, unpriced),
    )

    await sink.finalize(_call(), result)

    _, completion, items = storage.finalized[0]
    assert completion.coverage_status == "pricing_missing"
    assert completion.missing_cost_entries == 1
    assert completion.cost_nanos == sum(item.cost_nanos for item in items)


@pytest.mark.asyncio
async def test_finalize_collapses_non_reconciling_items_to_envelope() -> None:
    storage = _Storage()
    sink = SessionUsageEventSink(storage)
    result = _result()
    incomplete_item = replace(result.items[0], input_tokens=1, billed_cost_nanos=1)

    await sink.finalize(_call(), replace(result, items=(incomplete_item,)))

    _, completion, items = storage.finalized[0]
    assert len(items) == 1
    assert items[0].input_tokens == completion.input_tokens == 11
    assert items[0].cost_nanos == completion.cost_nanos == 9


@pytest.mark.asyncio
async def test_finalize_failure_schedules_bounded_idempotent_retry() -> None:
    storage = _Storage()
    storage.fail_finalize = 1
    sink = SessionUsageEventSink(storage, retry_delays=(0.0,))

    with pytest.raises(RuntimeError, match="busy"):
        await sink.finalize(_call(), _result())

    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert len(storage.finalized) == 1
    await sink.close()


@pytest.mark.asyncio
async def test_close_drains_retry_before_cancelling_background_tasks() -> None:
    storage = _Storage()
    storage.fail_finalize = 1
    sink = SessionUsageEventSink(storage, retry_delays=(0.01,))

    with pytest.raises(RuntimeError, match="busy"):
        await sink.finalize(_call(), _result())

    await sink.close()

    assert len(storage.finalized) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        ("provider_error:503", "provider_error:503"),
        ("provider_error:vendor-private-code", "provider_error"),
        ("provider_error:https://provider.invalid/?key=sk-secret", "provider_error"),
        ("provider_error:503\nsecret", "provider_error"),
        ("cancelled", "cancelled"),
        ("arbitrary internal detail", "usage_unknown"),
    ],
)
async def test_unknown_provider_receipt_is_explicitly_closed(
    reason: str,
    expected: str,
) -> None:
    storage = _Storage()
    sink = SessionUsageEventSink(storage)

    await sink.mark_unknown(_call(), reason)

    assert storage.unknown[0][0] == "event-1"
    assert storage.unknown[0][1] >= 1_000
    assert storage.unknown[0][2] == expected
