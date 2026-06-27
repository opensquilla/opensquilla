from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from opensquilla.cli.tui.backend.streaming import StreamingPlane
from opensquilla.cli.tui.backend.transcript import (
    MessageItem,
    RouterDecisionItem,
    ToolItem,
    ToolPreviewPolicy,
    TranscriptStore,
    ViewportRequest,
    build_args_preview,
    build_output_preview,
    project_viewport,
)
from opensquilla.cli.tui.renderers.selection import get_renderer_backend

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = PROJECT_ROOT / "tests" / "unit" / "cli" / "tui" / "replay_fixtures.py"
DENSE_HISTORY_VIEWPORT = ViewportRequest(scroll_offset=200, viewport_height=24, overscan=3)
DENSE_HISTORY_PREVIEW_POLICY = ToolPreviewPolicy()


@dataclass(frozen=True)
class ReplaySummary:
    renderer: str
    fixture: str
    event_count: int
    text_chars: int
    tool_count: int
    router_decision_count: int
    wall_ms: float
    flush_count: int
    max_buffer_chars: int
    coalescing_ratio: float
    transcript_items: int
    visible_items: int
    expanded_tools: int
    projection_wall_ms: float
    available: bool
    skip_reason: str | None
    rendered_text_matches: bool
    plugin_error_count: int
    errors: list[str]


class _ReplayStreamOutput:
    def __init__(self, output_handle: _ReplayOutputHandle) -> None:
        self._output_handle = output_handle

    async def __aenter__(self):
        return self._output_handle.write

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


class _ReplayOutputHandle:
    def __init__(self) -> None:
        self.flush_count = 0
        self.max_payload_chars = 0

    def write(self, payload: str) -> None:
        self.flush_count += 1
        self.max_payload_chars = max(self.max_payload_chars, len(payload))

    async def write_through(self, payload: str) -> None:
        self.write(payload)

    def stream_output(self) -> _ReplayStreamOutput:
        return _ReplayStreamOutput(self)


def _load_fixture_module() -> Any:
    spec = importlib.util.spec_from_file_location("tui_replay_fixtures", FIXTURE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load replay fixtures from {FIXTURE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _build_events(fixture: str) -> list[Any]:
    fixtures = _load_fixture_module()
    if fixture == "long-stream":
        return list(fixtures.build_long_stream_events())
    if fixture == "dense-history":
        return list(fixtures.build_dense_history_events())
    raise ValueError(f"Unsupported fixture: {fixture}")


def _expected_stream_text(events: list[Any]) -> str:
    return "".join(
        str(event.payload.get("text", ""))
        for event in events
        if event.kind == "text_delta"
    )


def _text_chars_for(event: Any) -> int:
    payload = event.payload
    if event.kind == "text_delta":
        return len(str(payload.get("text", "")))
    if event.kind == "history_message":
        return len(str(payload.get("content", "")))
    if event.kind == "tool_card":
        return len(str(payload.get("summary", "")))
    return 0


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _optional_float(value: object) -> float | None:
    if isinstance(value, int | float):
        return float(value)
    return None


def _int_or_default(value: object, default: int) -> int:
    if not isinstance(value, int | float | str | bytes | bytearray):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _append_transcript_event(store: TranscriptStore, event: Any) -> None:
    payload = event.payload
    if event.kind == "router_decision":
        store.append(
            RouterDecisionItem(
                tier=str(payload.get("tier", "")),
                model=str(payload.get("model", "")),
                baseline_model=_optional_str(payload.get("baseline_model")),
                confidence=_optional_float(payload.get("confidence")),
                rollout_phase=_optional_str(payload.get("rollout_phase")),
                timestamp_ms=event.timestamp_ms,
            )
        )
    elif event.kind == "history_message":
        store.append(
            MessageItem(
                role=str(payload.get("role", "")),
                text=str(payload.get("content", "")),
                run_id=None,
                timestamp_ms=event.timestamp_ms,
            )
        )
    elif event.kind == "tool_card":
        args_preview = build_args_preview(
            {
                "line_count": payload.get("line_count"),
                "rendered_bytes": payload.get("rendered_bytes"),
            },
            DENSE_HISTORY_PREVIEW_POLICY,
        )
        output_preview = build_output_preview(
            str(payload.get("summary", "")),
            DENSE_HISTORY_PREVIEW_POLICY,
        )
        store.append(
            ToolItem(
                tool_id=str(payload.get("tool_use_id", "")),
                name=str(payload.get("name", "tool")),
                status="done",
                args_preview=args_preview.text,
                output_preview=output_preview.text,
                expanded=bool(payload.get("expanded_candidate", False)),
                timestamp_ms=event.timestamp_ms,
                detail_line_count=_int_or_default(payload.get("line_count"), 1),
            )
        )


async def _flush_streaming_plane(
    renderer: Any,
    streaming_plane: StreamingPlane,
) -> None:
    flush = streaming_plane.finish()
    if flush is not None:
        await renderer.aappend_text(flush.text)


async def _render_event(
    renderer: Any,
    streaming_plane: StreamingPlane,
    event: Any,
) -> None:
    payload = event.payload
    if event.kind == "text_delta":
        flush = streaming_plane.append(str(payload.get("text", "")))
        if flush is not None:
            await renderer.aappend_text(flush.text)
    elif event.kind == "tool_start":
        await _flush_streaming_plane(renderer, streaming_plane)
        args = payload.get("args")
        await renderer.atool_start(
            str(payload.get("name", "tool")),
            args if isinstance(args, dict) else None,
            str(payload.get("tool_use_id", "")),
        )
    elif event.kind == "tool_finished":
        await _flush_streaming_plane(renderer, streaming_plane)
        elapsed = payload.get("elapsed")
        await renderer.atool_finished(
            str(payload.get("tool_use_id", "")),
            success=bool(payload.get("success", True)),
            elapsed=elapsed if isinstance(elapsed, float) else None,
            error=str(payload["error"]) if "error" in payload else None,
        )
    elif event.kind == "router_decision":
        await _flush_streaming_plane(renderer, streaming_plane)
        await renderer.astatus(
            "route: "
            f"{payload.get('tier')} -> {payload.get('model')} "
            f"(baseline {payload.get('baseline_model')})",
            style="cyan",
        )
    elif event.kind == "history_message":
        await _flush_streaming_plane(renderer, streaming_plane)
        await renderer.astatus(
            f"{payload.get('role')}: {str(payload.get('content', ''))[:120]}",
            style="dim",
        )
    elif event.kind == "tool_card":
        await _flush_streaming_plane(renderer, streaming_plane)
        await renderer.astatus(
            f"tool: {payload.get('name')} {payload.get('summary')}",
            style="magenta",
        )
    elif event.kind == "done":
        await _flush_streaming_plane(renderer, streaming_plane)
        await renderer.afinalize()


async def run_replay(renderer: str, fixture: str, *, repeat: int = 1) -> ReplaySummary:
    if repeat < 1:
        raise ValueError("--repeat must be >= 1")
    backend = get_renderer_backend(renderer)

    errors: list[str] = []
    event_count = 0
    text_chars = 0
    tool_count = 0
    router_decision_count = 0
    text_delta_count = 0
    streaming_flush_count = 0
    flush_count = 0
    max_buffer_chars = 0
    transcript_items = 0
    visible_items = 0
    expanded_tools = 0
    projection_wall_ms = 0.0
    rendered_text_matches = True
    started_at = time.perf_counter()

    for _ in range(repeat):
        events = _build_events(fixture)
        output_handle = _ReplayOutputHandle() if fixture == "long-stream" else None
        replay_renderer = (
            backend.create_renderer(title="tui-replay", output_handle=output_handle)
            if fixture == "long-stream"
            else None
        )
        streaming_plane = StreamingPlane()
        transcript_store = TranscriptStore() if fixture == "dense-history" else None
        for event in events:
            event_count += 1
            text_chars += _text_chars_for(event)
            if event.kind == "text_delta":
                text_delta_count += 1
            if event.kind in {"tool_start", "tool_card"}:
                tool_count += 1
            if event.kind == "router_decision":
                router_decision_count += 1
            try:
                if transcript_store is not None:
                    _append_transcript_event(transcript_store, event)
                elif replay_renderer is not None:
                    await _render_event(replay_renderer, streaming_plane, event)
            except Exception as exc:  # pragma: no cover - summarized for CLI evidence.
                errors.append(f"{event.kind}: {exc}")
            max_buffer_chars = max(
                max_buffer_chars,
                streaming_plane.max_buffer_chars,
            )
        if replay_renderer is not None:
            await replay_renderer.aclose()
            rendered_text_matches = rendered_text_matches and (
                getattr(replay_renderer, "buffer", "") == _expected_stream_text(events)
            )
        if transcript_store is not None:
            snapshot = transcript_store.snapshot()
            projection_started_at = time.perf_counter()
            projection = project_viewport(snapshot, DENSE_HISTORY_VIEWPORT)
            projection_wall_ms += (
                time.perf_counter() - projection_started_at
            ) * 1_000
            transcript_items += len(snapshot)
            visible_items += len(projection.items)
            expanded_tools += sum(
                1 for item in snapshot if isinstance(item, ToolItem) and item.expanded
            )
        streaming_flush_count += streaming_plane.flush_count
        if output_handle is not None:
            flush_count += output_handle.flush_count
        elif replay_renderer is not None:
            flush_count += int(getattr(replay_renderer, "flush_count", 0))

    wall_ms = (time.perf_counter() - started_at) * 1_000
    coalescing_ratio = (
        round(streaming_flush_count / text_delta_count, 6)
        if text_delta_count > 0
        else 0.0
    )
    return ReplaySummary(
        renderer=renderer,
        fixture=fixture,
        event_count=event_count,
        text_chars=text_chars,
        tool_count=tool_count,
        router_decision_count=router_decision_count,
        wall_ms=round(wall_ms, 3),
        flush_count=flush_count,
        max_buffer_chars=max_buffer_chars,
        coalescing_ratio=coalescing_ratio,
        transcript_items=transcript_items,
        visible_items=visible_items,
        expanded_tools=expanded_tools,
        projection_wall_ms=round(projection_wall_ms, 3),
        available=True,
        skip_reason=None,
        rendered_text_matches=rendered_text_matches,
        plugin_error_count=0,
        errors=errors,
    )


def write_summary(summary: ReplaySummary, summary_json: Path) -> None:
    summary_json.parent.mkdir(parents=True, exist_ok=True)
    summary_json.write_text(json.dumps(asdict(summary), indent=2, sort_keys=True) + "\n")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Replay synthetic TUI events.")
    parser.add_argument("--renderer", choices=("opentui",), required=True)
    parser.add_argument("--fixture", choices=("long-stream", "dense-history"), required=True)
    parser.add_argument("--summary-json", type=Path, required=True)
    parser.add_argument("--repeat", type=int, default=1)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    summary = asyncio.run(
        run_replay(args.renderer, args.fixture, repeat=args.repeat),
    )
    write_summary(summary, args.summary_json)
    return 1 if summary.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
