from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest

from opensquilla.cli.chat.turn_stream import _drain_stalled_planes
from opensquilla.cli.tui.backend import domain_events, plugins
from opensquilla.cli.tui.backend import runtime as backend_runtime
from opensquilla.cli.tui.backend.contracts import (
    TuiInputKind,
    TuiRuntimeConfig,
    TuiRuntimeHooks,
)
from opensquilla.cli.tui.backend.directives import StreamDirectiveFilter
from opensquilla.cli.tui.backend.domain_events import TuiDomainEvent, now_ms
from opensquilla.cli.tui.backend.events import (
    TUI_DOMAIN_EVENT_KINDS,
    TuiEvent,
    TuiEventKind,
)
from opensquilla.cli.tui.backend.plugins import TuiPluginContext, TuiPluginManager
from opensquilla.cli.tui.backend.render_summary import (
    TOOL_SUMMARY_ARG_KEYS,
    clip_arg,
    sanitize_terminal_text,
    summarize_args,
    summarize_result,
)
from opensquilla.cli.tui.backend.runtime import run_tui_runtime
from opensquilla.cli.tui.backend.state import TuiRuntimeState
from opensquilla.cli.tui.backend.streaming import StreamingFlushPolicy, StreamingPlane
from opensquilla.cli.tui.backend.transcript import (
    ToolItem,
    ToolPreviewPolicy,
    TranscriptStore,
    build_args_preview,
    build_output_preview,
)


class _FakeSurface:
    def __init__(self, inputs: asyncio.Queue[str | None]) -> None:
        self._inputs = inputs
        self.cancel_callbacks: list[Any] = []
        self.shutdown_callbacks: list[Any] = []
        self.writes: list[str] = []

    async def next_line(self) -> str | None:
        return await self._inputs.get()

    def set_cancel_callback(self, cb) -> None:  # noqa: ANN001
        self.cancel_callbacks.append(cb)

    def set_shutdown_callback(self, cb) -> None:  # noqa: ANN001
        self.shutdown_callbacks.append(cb)

    def emit_eof(self) -> None:
        self._inputs.put_nowait(None)

    async def write_through(self, payload: str) -> None:
        self.writes.append(payload)

    @property
    def redraw_callback(self) -> Callable[[], None]:
        return lambda: None


def _surface_factory(surface: _FakeSurface):
    @asynccontextmanager
    async def _factory() -> AsyncIterator[_FakeSurface]:
        yield surface

    return _factory


async def _echo(surface: Any, text: str) -> None:
    await surface.write_through(f"echo:{text}")


async def _queued_echo(surface: Any) -> None:
    await surface.write_through("queued")


async def _wait_until(predicate: Callable[[], bool], *, timeout: float = 2.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() >= deadline:
            raise AssertionError("timed out waiting for runtime condition")
        await asyncio.sleep(0)


def _runtime_config(**kwargs: Any) -> TuiRuntimeConfig:
    return TuiRuntimeConfig(task_name="chat-turn-hardening", **kwargs)


def _runtime_hooks(**kwargs: Any) -> TuiRuntimeHooks:
    return TuiRuntimeHooks(
        on_user_input_echo=_echo,
        on_queued_turn_start=_queued_echo,
        **kwargs,
    )


class MutableClock:
    def __init__(self) -> None:
        self.value = 0

    def __call__(self) -> int:
        return self.value

    def advance(self, milliseconds: int) -> None:
        self.value += milliseconds


# ---------------------------------------------------------------------------
# runtime loop survival
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runtime_survives_dispatch_exception_and_keeps_looping() -> None:
    inputs: asyncio.Queue[str | None] = asyncio.Queue()
    surface = _FakeSurface(inputs)
    executed: list[str] = []
    notices: list[str] = []

    async def _dispatch(user_input: str) -> bool:
        executed.append(user_input)
        if user_input == "boom":
            raise ConnectionError("gateway lost: [conn]")
        return True

    task = asyncio.create_task(
        run_tui_runtime(
            dispatch=_dispatch,
            surface_factory=_surface_factory(surface),
            config=_runtime_config(),
            hooks=_runtime_hooks(notice=notices.append),
        )
    )

    await inputs.put("boom")
    await _wait_until(lambda: any("Turn failed" in notice for notice in notices))
    await inputs.put("after")
    await _wait_until(lambda: "after" in executed)
    await inputs.put(None)
    result = await asyncio.wait_for(task, timeout=2.0)

    assert isinstance(result, TuiRuntimeState)
    assert executed == ["boom", "after"]
    # dynamic error text is markup-escaped so the notice itself cannot crash.
    assert any("\\[conn]" in notice for notice in notices)


@pytest.mark.asyncio
async def test_runtime_survives_dispatch_exception_on_destructive_command() -> None:
    inputs: asyncio.Queue[str | None] = asyncio.Queue()
    surface = _FakeSurface(inputs)
    executed: list[str] = []
    notices: list[str] = []

    async def _dispatch(user_input: str) -> bool:
        executed.append(user_input)
        if user_input == "/clear":
            raise RuntimeError("rpc unavailable")
        return True

    task = asyncio.create_task(
        run_tui_runtime(
            dispatch=_dispatch,
            surface_factory=_surface_factory(surface),
            config=_runtime_config(
                classify_input=lambda text: (
                    TuiInputKind.DESTRUCTIVE if text == "/clear" else TuiInputKind.NORMAL
                )
            ),
            hooks=_runtime_hooks(notice=notices.append),
        )
    )

    await inputs.put("/clear")
    await _wait_until(lambda: any("Turn failed" in notice for notice in notices))
    await inputs.put("after")
    await _wait_until(lambda: "after" in executed)
    await inputs.put(None)
    await asyncio.wait_for(task, timeout=2.0)

    assert executed == ["/clear", "after"]


@pytest.mark.asyncio
async def test_runtime_emits_turn_cancelled_for_destructive_cancel() -> None:
    inputs: asyncio.Queue[str | None] = asyncio.Queue()
    surface = _FakeSurface(inputs)
    events: list[TuiEvent] = []
    first_started = asyncio.Event()
    clear_done = asyncio.Event()

    async def _dispatch(user_input: str) -> bool:
        if user_input == "first":
            first_started.set()
            await asyncio.sleep(5)
        if user_input == "/clear":
            clear_done.set()
        return True

    task = asyncio.create_task(
        run_tui_runtime(
            dispatch=_dispatch,
            surface_factory=_surface_factory(surface),
            config=_runtime_config(
                event_sink=events.append,
                classify_input=lambda text: (
                    TuiInputKind.DESTRUCTIVE if text == "/clear" else TuiInputKind.NORMAL
                ),
            ),
            hooks=_runtime_hooks(),
        )
    )

    await inputs.put("first")
    await asyncio.wait_for(first_started.wait(), timeout=2.0)
    await inputs.put("/clear")
    await asyncio.wait_for(clear_done.wait(), timeout=2.0)
    await inputs.put(None)
    await asyncio.wait_for(task, timeout=2.0)

    assert TuiEventKind.TURN_CANCELLED in [event.kind for event in events]


@pytest.mark.asyncio
async def test_runtime_degrades_cleanly_when_echo_hook_fails() -> None:
    inputs: asyncio.Queue[str | None] = asyncio.Queue()
    surface = _FakeSurface(inputs)
    notices: list[str] = []
    executed: list[str] = []

    async def _dispatch(user_input: str) -> bool:
        executed.append(user_input)
        return True

    async def _raising_echo(_surface: Any, _text: str) -> None:
        raise RuntimeError("host write failed: [io]")

    await inputs.put("hello")
    result = await asyncio.wait_for(
        run_tui_runtime(
            dispatch=_dispatch,
            surface_factory=_surface_factory(surface),
            config=_runtime_config(),
            hooks=TuiRuntimeHooks(
                on_user_input_echo=_raising_echo,
                on_queued_turn_start=_queued_echo,
                notice=notices.append,
            ),
        ),
        timeout=2.0,
    )

    assert isinstance(result, TuiRuntimeState)
    assert executed == []
    assert any("Input surface error" in notice for notice in notices)
    assert any("\\[io]" in notice for notice in notices)


@pytest.mark.asyncio
async def test_runtime_drains_pending_abort_task_before_returning() -> None:
    inputs: asyncio.Queue[str | None] = asyncio.Queue()
    surface = _FakeSurface(inputs)
    aborts: list[str] = []
    dispatch_started = asyncio.Event()

    async def _dispatch(_user_input: str) -> bool:
        dispatch_started.set()
        await asyncio.sleep(5)
        return True

    async def _cancel_active_turn() -> None:
        await asyncio.sleep(0.05)
        aborts.append("delivered")

    task = asyncio.create_task(
        run_tui_runtime(
            dispatch=_dispatch,
            surface_factory=_surface_factory(surface),
            config=_runtime_config(),
            hooks=_runtime_hooks(on_cancel_active_turn=_cancel_active_turn),
        )
    )

    await inputs.put("hello")
    await asyncio.wait_for(dispatch_started.wait(), timeout=2.0)
    active_cb = next(cb for cb in reversed(surface.cancel_callbacks) if cb is not None)
    active_cb()
    await inputs.put(None)
    await asyncio.wait_for(task, timeout=2.0)

    # The cancel-then-exit abort RPC must complete before the runtime returns,
    # not be abandoned as an unreferenced task.
    assert aborts == ["delivered"]


@pytest.mark.asyncio
async def test_runtime_bounds_shutdown_drain_when_abort_rpc_never_resolves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(backend_runtime, "_ABORT_DRAIN_TIMEOUT_S", 0.05)
    inputs: asyncio.Queue[str | None] = asyncio.Queue()
    surface = _FakeSurface(inputs)
    dispatch_started = asyncio.Event()
    abort_cancelled = asyncio.Event()

    async def _dispatch(_user_input: str) -> bool:
        dispatch_started.set()
        await asyncio.sleep(5)
        return True

    async def _wedged_abort() -> None:
        # An abort RPC whose response frame never arrives (wedged gateway).
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            abort_cancelled.set()
            raise

    task = asyncio.create_task(
        run_tui_runtime(
            dispatch=_dispatch,
            surface_factory=_surface_factory(surface),
            config=_runtime_config(),
            hooks=_runtime_hooks(on_cancel_active_turn=_wedged_abort),
        )
    )

    await inputs.put("hello")
    await asyncio.wait_for(dispatch_started.wait(), timeout=2.0)
    active_cb = next(cb for cb in reversed(surface.cancel_callbacks) if cb is not None)
    active_cb()
    await inputs.put(None)

    # Exit must complete promptly despite the unanswered abort RPC, and the
    # straggler abort task must be cancelled rather than awaited forever.
    result = await asyncio.wait_for(task, timeout=2.0)
    assert isinstance(result, TuiRuntimeState)
    await asyncio.wait_for(abort_cancelled.wait(), timeout=2.0)


# ---------------------------------------------------------------------------
# streaming plane
# ---------------------------------------------------------------------------


def test_streaming_plane_size_overflow_keeps_buffer_bounded_and_tail_drainable() -> None:
    clock = MutableClock()
    plane = StreamingPlane(
        policy=StreamingFlushPolicy(max_delay_ms=10_000, max_chars=10, newline_min_chars=1_000),
        clock_ms=clock,
    )

    assert plane.append("abcdefgh") is None
    flush = plane.append("ijklm")

    assert flush is not None
    assert flush.text == "abcdefgh"
    assert flush.reason == "size"
    assert flush.delta_count == 1
    assert plane.max_buffer_chars <= 10
    tail = plane.finish()
    assert tail is not None
    assert tail.text == "ijklm"
    assert tail.delta_count == 1


def test_streaming_plane_overflow_delta_with_own_flush_condition_drains_immediately() -> None:
    clock = MutableClock()
    plane = StreamingPlane(
        policy=StreamingFlushPolicy(max_delay_ms=10_000, max_chars=10, newline_min_chars=2),
        clock_ms=clock,
    )

    assert plane.append("abcdefgh") is None
    flush = plane.append("ij\n")

    # The delta carries its own flush condition (newline past the minimum), so
    # it must not be retained unrendered behind the size flush.
    assert flush is not None
    assert flush.text == "abcdefghij\n"
    assert flush.delta_count == 2
    assert plane.finish() is None


def test_streaming_plane_flush_drains_stale_buffer_for_heartbeats() -> None:
    clock = MutableClock()
    plane = StreamingPlane(
        policy=StreamingFlushPolicy(max_delay_ms=33, max_chars=100, newline_min_chars=100),
        clock_ms=clock,
    )

    assert plane.append("tail") is None
    assert plane.flush() is None  # delay budget not exhausted yet

    clock.advance(34)
    flush = plane.flush()

    assert flush is not None
    assert flush.text == "tail"
    assert flush.reason == "delay"
    assert plane.flush() is None  # buffer drained


def test_streaming_flush_reports_deltas_coalesced_per_flush() -> None:
    clock = MutableClock()
    events: list[TuiDomainEvent] = []
    plane = StreamingPlane(
        policy=StreamingFlushPolicy(max_delay_ms=10_000, max_chars=6, newline_min_chars=1_000),
        clock_ms=clock,
        event_sink=events.append,
    )

    assert plane.append("ab") is None
    assert plane.append("cd") is None
    first = plane.append("ef")
    assert plane.append("gh") is None
    second = plane.append("ijkl")

    assert first is not None and first.delta_count == 3
    assert second is not None and second.delta_count == 2
    assert plane.delta_count == 5  # plane attribute stays cumulative
    assert [event.payload["delta_count"] for event in events] == [3, 2]
    assert [event.payload["flush_count"] for event in events] == [1, 2]


class _PlaneRecordingRenderer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def aappend_text(self, text: str, presentation: str = "answer") -> None:
        self.calls.append(("text", text))

    async def aappend_reasoning(self, text: str) -> None:
        self.calls.append(("reasoning", text))


@pytest.mark.asyncio
async def test_heartbeat_drain_holds_text_tail_while_reasoning_is_mid_stream() -> None:
    clock = MutableClock()
    policy = StreamingFlushPolicy(max_delay_ms=33, max_chars=2_048, newline_min_chars=256)
    text_plane = StreamingPlane(policy=policy, clock_ms=clock)
    reasoning_plane = StreamingPlane(policy=policy, clock_ms=clock)
    renderer = _PlaneRecordingRenderer()

    assert text_plane.append("answer tail") is None
    assert reasoning_plane.append("mid-thought") is None
    clock.advance(34)  # both tails now satisfy the stalled-delay condition

    # While reasoning is mid-stream the buffered text tail must stay buffered:
    # rendering it would close the open thinking marker and split the thought
    # into two blocks.
    await _drain_stalled_planes(renderer, text_plane, reasoning_plane, reasoning_mid_stream=True)
    assert renderer.calls == [("reasoning", "mid-thought")]

    # Once reasoning is no longer the active stream the tail drains normally.
    clock.advance(34)
    await _drain_stalled_planes(renderer, text_plane, reasoning_plane, reasoning_mid_stream=False)
    assert renderer.calls == [("reasoning", "mid-thought"), ("text", "answer tail")]


# ---------------------------------------------------------------------------
# render_summary sanitization
# ---------------------------------------------------------------------------


def test_sanitizer_strips_unterminated_string_sequences() -> None:
    assert sanitize_terminal_text("\x1b]0;evil title") == ""
    assert sanitize_terminal_text("\x1bPq#0;2;0;0;0 payload") == ""
    assert sanitize_terminal_text("\x1bXsos payload") == ""
    # a sequence cut mid-way must not swallow the lines that follow it
    assert sanitize_terminal_text("\x1b]0;cut\nreal output") == "\nreal output"


def test_sanitizer_strips_terminated_apc_pm_sos_payloads() -> None:
    assert sanitize_terminal_text("\x1b_Ga=T,f=100;QUJDREVGRw==\x1b\\after") == "after"
    assert sanitize_terminal_text("\x1b^privacy message\x1b\\ok") == "ok"
    assert sanitize_terminal_text("\x1bXstart of string\x1b\\done") == "done"


def test_sanitizer_strips_8bit_c1_controls() -> None:
    assert sanitize_terminal_text("\x9b31mred\x9b0m plain") == "red plain"
    assert sanitize_terminal_text("\x9d0;title\x9cok") == "ok"
    assert sanitize_terminal_text("a\x85b\x9cc") == "abc"
    assert summarize_result("\x9b31mred\x9b0m plain") == "red plain"


# ---------------------------------------------------------------------------
# render_summary tool-arg summaries
# ---------------------------------------------------------------------------


def test_summarize_args_apply_patch_shows_first_target_file() -> None:
    patch = (
        "*** Begin Patch\n"
        "*** Update File: src/app.py\n"
        "@@@ hunk\n"
        "*** Delete File: src/old.py\n"
        "*** End Patch"
    )
    assert summarize_args("apply_patch", {"patch": patch}) == "src/app.py"
    assert (
        summarize_args("apply_patch", {"patch": "*** Begin Patch\n*** Add File: pkg/new.py"})
        == "pkg/new.py"
    )
    assert summarize_args("apply_patch", {"patch": "no file markers"}) == ""
    assert summarize_args("apply_patch", {}) == ""


def test_summarize_args_generic_fallback_covers_unlisted_tools() -> None:
    assert summarize_args("edit_file", {"path": "/ws/notes.txt", "old_text": "a"}) == (
        "/ws/notes.txt"
    )
    assert summarize_args("grep_search", {"pattern": "TODO"}) == "TODO"
    assert summarize_args("http_request", {"url": "https://example.com"}) == (
        "https://example.com"
    )
    assert summarize_args("unknown_tool", {"blob": "x"}) == ""


def test_summarize_args_generic_fallback_flattens_multiline_values() -> None:
    # The tool row is a single line: multiline code/command values must not
    # leak raw newlines into it.
    assert summarize_args("run_python", {"code": "print(1)\nprint(2)"}) == "print(1) print(2)"
    assert summarize_args("custom_exec", {"command": "ls -a\n\techo done"}) == "ls -a echo done"
    long_summary = summarize_args("custom_exec", {"command": "a\n" + "b" * 200})
    assert "\n" not in long_summary
    assert summarize_args("custom_exec", {"command": " \n \n "}) == ""


def test_summarize_args_names_conform_to_builtin_registry() -> None:
    import opensquilla.tools.builtin  # noqa: F401 - registers the builtin tools
    from opensquilla.tools.registry import get_default_registry

    registry = get_default_registry()
    samples = {"patch": "*** Begin Patch\n*** Update File: pkg/mod.py\n*** End Patch"}
    for name, keys in TOOL_SUMMARY_ARG_KEYS.items():
        registered = registry.get(name)
        assert registered is not None, f"summarize_args names unknown tool {name!r}"
        for key in keys:
            assert key in registered.spec.parameters, (
                f"tool {name!r} does not declare summarized argument {key!r}"
            )
        value = samples.get(keys[0], "sample-value")
        assert summarize_args(name, {keys[0]: value}), (
            f"tool {name!r} renders an empty arg summary"
        )


# ---------------------------------------------------------------------------
# render_summary cell-aware clipping
# ---------------------------------------------------------------------------


def test_clip_arg_clips_by_display_cells_not_code_points() -> None:
    wide = "汉" * 60  # 120 terminal cells
    clipped = clip_arg(wide, limit=90)
    assert clipped == "汉" * 43 + "..."

    tail_clipped = clip_arg(wide, limit=90, keep_end=True)
    assert tail_clipped == "..." + "汉" * 43

    ascii_value = "a" * 90
    assert clip_arg(ascii_value, limit=90) == ascii_value


def test_clip_arg_never_splits_emoji_clusters() -> None:
    cluster = "\U0001f469\u200d\U0001f469"

    clipped = clip_arg("a" * 88 + cluster, limit=90)
    assert clipped == "a" * 87 + "..."
    assert "\u200d" not in clipped

    leading = clip_arg(cluster + "a" * 100, limit=20)
    assert leading.startswith(cluster)
    assert leading == cluster + "a" * 13 + "..."


# ---------------------------------------------------------------------------
# render_summary short results
# ---------------------------------------------------------------------------


def test_summarize_result_keeps_sole_short_results() -> None:
    assert summarize_result("7\nexit_code=0") == "7"
    assert summarize_result("y") == "y"
    assert summarize_result("!!") == "!!"


def test_summarize_result_still_drops_noise_next_to_meaningful_lines() -> None:
    assert summarize_result("exit_code=0\n.\nagents") == "agents"
    assert summarize_result("exit_code=0") == ""


def test_summarize_result_prefers_meaningful_short_line_over_punctuation_noise() -> None:
    # The computed value usually trails the noise: a spinner/separator line
    # must not win over the short result the fallback exists to preserve.
    assert summarize_result("...\n7") == "7"
    assert summarize_result("exit_code=0\n...\n7") == "7"
    assert summarize_result("7\n...") == "7"
    # With nothing but punctuation on offer, the first line still renders.
    assert summarize_result("...\n??") == "..."


# ---------------------------------------------------------------------------
# domain event kind registry
# ---------------------------------------------------------------------------


def test_domain_event_kind_registry_contains_every_kind_constant() -> None:
    kind_values = {
        value
        for name, value in vars(domain_events).items()
        if name.startswith("KIND_") and isinstance(value, str)
    }
    assert kind_values == set(TUI_DOMAIN_EVENT_KINDS)
    assert domain_events.KIND_REASONING_FLUSH in TUI_DOMAIN_EVENT_KINDS
    assert domain_events.KIND_REASONING_DELTA in TUI_DOMAIN_EVENT_KINDS


# ---------------------------------------------------------------------------
# plugin error ledger
# ---------------------------------------------------------------------------


class _ExplodingPlugin:
    plugin_id = "exploding"
    slots: frozenset[str] = frozenset()

    def on_event(self, event: TuiDomainEvent, context: TuiPluginContext) -> None:
        raise RuntimeError("plugin exploded")

    def snapshot(self, slot: str) -> object | None:
        return None


class _LogStub:
    def __init__(self) -> None:
        self.warnings: list[tuple[str, dict[str, Any]]] = []

    def warning(self, event: str, **kwargs: Any) -> None:
        self.warnings.append((event, kwargs))


def _status_event() -> TuiDomainEvent:
    return TuiDomainEvent(
        kind="status",
        source="runtime",
        payload={},
        turn_id=None,
        timestamp_ms=now_ms(),
    )


def test_plugin_error_ledger_is_bounded_and_warns_once_per_plugin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _LogStub()
    monkeypatch.setattr(plugins, "log", stub)
    manager = TuiPluginManager([_ExplodingPlugin()])

    for _ in range(plugins._MAX_RECORDED_ERRORS + 50):
        manager.dispatch(_status_event())

    assert len(manager.errors) == plugins._MAX_RECORDED_ERRORS
    assert [event for event, _ in stub.warnings] == ["tui_plugin.error"]
    assert stub.warnings[0][1]["plugin_id"] == "exploding"


# ---------------------------------------------------------------------------
# transcript previews and ids
# ---------------------------------------------------------------------------


def test_tool_previews_degrade_on_non_json_serializable_values() -> None:
    policy = ToolPreviewPolicy()

    args_preview = build_args_preview({"path": Path("/ws/sample.txt")}, policy)
    assert "sample.txt" in args_preview.text

    output_preview = build_output_preview(b"binary blob", policy)
    assert "binary blob" in output_preview.text

    circular: dict[str, object] = {}
    circular["self"] = circular
    assert build_args_preview(circular, policy).text


def test_tool_previews_strip_terminal_controls() -> None:
    policy = ToolPreviewPolicy()

    output_preview = build_output_preview("\x1b[31mred\x1b[0m done", policy)
    assert output_preview.text == "red done"

    args_preview = build_args_preview({"note": "\x9b31mred"}, policy)
    assert "red" in args_preview.text
    assert "\x9b" not in args_preview.text


def _tool_item(tool_id: str, status: str) -> ToolItem:
    return ToolItem(
        tool_id=tool_id,
        name="search",
        status=status,
        args_preview="{}",
        output_preview="",
        expanded=False,
        timestamp_ms=1,
    )


def test_transcript_store_uniquifies_repeated_tool_ids() -> None:
    store = TranscriptStore()

    first = store.append(_tool_item("call-1", "running"))
    second = store.append(_tool_item("call-1", "done"))
    third = store.append(_tool_item("call-1", "done"))

    assert first.item_id == "tool-call-1"
    assert second.item_id == "tool-call-1-2"
    assert third.item_id == "tool-call-1-3"
    assert len({item.item_id for item in store.snapshot()}) == 3

    store.clear()
    again = store.append(_tool_item("call-1", "running"))
    assert again.item_id == "tool-call-1"


# ---------------------------------------------------------------------------
# StreamDirectiveFilter (backend/directives.py)
# ---------------------------------------------------------------------------


def _filtered(deltas: list[str]) -> str:
    stream_filter = StreamDirectiveFilter()
    visible = "".join(stream_filter.feed(delta) for delta in deltas)
    return visible + stream_filter.flush()


def test_directive_filter_strips_whole_and_split_tags() -> None:
    assert _filtered(["[[reply_to_current]]\nhello"]) == "hello"
    assert _filtered(["[reply_to_current]\nhello"]) == "hello"
    assert _filtered(["[[reply_to", "_current]]", " hi"]) == "hi"
    assert _filtered(["[[reply_to_current]", "]", "answer"]) == "answer"
    assert _filtered(["[[reply_to: chat-42]] body"]) == "body"
    assert _filtered(["pre [[reply_to_current]] post"]) == "pre post"
    assert _filtered(list("[[reply_to_current]] char by char")) == "char by char"


def test_directive_filter_keeps_ordinary_bracketed_text() -> None:
    assert _filtered(["a [link](url) stays"]) == "a [link](url) stays"
    assert _filtered(["array[0] = 1"]) == "array[0] = 1"
    assert _filtered(["[re", "gular text]"]) == "[regular text]"
    assert _filtered(["[reply_to_curious]"]) == "[reply_to_curious]"
    # An unbalanced close can no longer become a tag — rendered literally.
    assert _filtered(["[[reply_to_current]x leak"]) == "[[reply_to_current]x leak"


def test_directive_filter_flush_releases_unfinished_prefix() -> None:
    stream_filter = StreamDirectiveFilter()
    assert stream_filter.feed("ends with [[re") == "ends with "
    assert stream_filter.flush() == "[[re"
