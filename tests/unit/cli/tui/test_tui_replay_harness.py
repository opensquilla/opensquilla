from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[4]
BENCH_SCRIPT = PROJECT_ROOT / "scripts" / "bench_tui_replay.py"
FIXTURE_MODULE = Path(__file__).with_name("replay_fixtures.py")


def _load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


fixtures = _load_module("tui_replay_fixtures", FIXTURE_MODULE)
ReplayEvent = fixtures.ReplayEvent
build_dense_history_events = fixtures.build_dense_history_events
build_long_stream_events = fixtures.build_long_stream_events


def _events_by_kind(events: list[Any], kind: str) -> list[Any]:
    return [event for event in events if event.kind == kind]


def _text_chars(events: list[ReplayEvent]) -> int:
    return sum(
        len(str(event.payload["text"]))
        for event in events
        if event.kind == "text_delta"
    )


def test_long_stream_fixture_matches_baseline_shape() -> None:
    events = build_long_stream_events()

    assert all(isinstance(event, ReplayEvent) for event in events)
    assert events[0].kind == "user_input"
    assert events[1].kind == "router_decision"
    assert events[-1].kind == "done"
    assert len(_events_by_kind(events, "text_delta")) == 4_000
    assert _text_chars(events) == 160_000
    assert len(_events_by_kind(events, "tool_start")) == 4
    assert len(_events_by_kind(events, "tool_finished")) == 4
    assert len(_events_by_kind(events, "router_decision")) == 1


def test_dense_history_fixture_matches_baseline_shape() -> None:
    events = build_dense_history_events()

    messages = _events_by_kind(events, "history_message")
    tool_cards = _events_by_kind(events, "tool_card")
    text_chars = sum(
        len(str(event.payload["content"]))
        for event in messages
        if "content" in event.payload
    )

    assert len(messages) == 500
    assert sum(1 for event in messages if event.payload["role"] == "user") == 250
    assert sum(1 for event in messages if event.payload["role"] == "assistant") == 250
    assert len(tool_cards) == 120
    assert sum(1 for event in tool_cards if event.payload["expanded_candidate"]) == 20
    assert len(_events_by_kind(events, "router_decision")) == 4
    assert text_chars >= 24 * 80 * 30


def test_opentui_replay_summary_can_be_written(tmp_path) -> None:
    bench = _load_module("bench_tui_replay", BENCH_SCRIPT)
    summary = asyncio.run(bench.run_replay("opentui", "long-stream", repeat=1))
    summary_path = tmp_path / "summary.json"

    bench.write_summary(summary, summary_path)

    data = json.loads(summary_path.read_text())
    assert data["renderer"] == "opentui"
    assert data["fixture"] == "long-stream"
    assert data["event_count"] == 4011
    assert data["text_chars"] == 160_000
    assert data["tool_count"] == 4
    assert data["router_decision_count"] == 1
    assert data["flush_count"] == 0
    assert 0 < data["coalescing_ratio"] < 1
    assert data["max_buffer_chars"] <= 2_048
    assert data["transcript_items"] == 0
    assert data["visible_items"] == 0
    assert data["expanded_tools"] == 0
    assert data["projection_wall_ms"] == 0
    assert data["available"] is True
    assert data["skip_reason"] is None
    assert data["rendered_text_matches"] is True
    assert data["plugin_error_count"] == 0
    assert data["errors"] == []


def test_dense_history_replay_uses_bounded_transcript_projection() -> None:
    bench = _load_module("bench_tui_replay", BENCH_SCRIPT)
    summary = asyncio.run(bench.run_replay("opentui", "dense-history", repeat=1))

    assert summary.event_count == 624
    assert summary.text_chars >= 24 * 80 * 30
    assert summary.tool_count == 120
    assert summary.router_decision_count == 4
    assert summary.flush_count == 0
    assert summary.coalescing_ratio == 0
    assert summary.transcript_items == 624
    assert 0 < summary.visible_items <= 30
    assert summary.expanded_tools == 20
    assert summary.projection_wall_ms >= 0
    assert summary.errors == []
