from __future__ import annotations

import io
from unittest.mock import patch

import pytest
from rich.console import Console
from rich.panel import Panel

from opensquilla.cli.repl import stream as stream_module
from opensquilla.cli.repl.stream import StreamingRenderer, UsageSummary, WaitingIndicator


def test_verb_cycles_by_dwell_seconds() -> None:
    ind = WaitingIndicator(started_at=100.0)
    assert ind._verb(0.0) == "Burrowing"
    assert ind._verb(2.6) == "Lurking"
    assert ind._verb(5.1) == "Scanning"
    n = len(WaitingIndicator._verbs)
    assert ind._verb(n * 2.5 + 0.1) == ind._verb(0.1)


def test_render_contains_verb_and_elapsed_seconds() -> None:
    started = 100.0
    ind = WaitingIndicator(started_at=started)
    with patch("opensquilla.cli.repl.stream.time.monotonic", return_value=started + 3.0):
        plain = ind.__rich__().plain
    # 3.0 / 2.5 = 1 → _verbs[1] == "Lurking"
    assert "Lurking" in plain
    assert "3.0s" in plain
    assert "Ctrl+C cancels" in plain


def test_pulse_restart_preserves_monotonic_elapsed() -> None:
    started = 100.0
    first = WaitingIndicator(started_at=started)
    second = WaitingIndicator(started_at=started)  # mirrors pulse() re-init
    with patch("opensquilla.cli.repl.stream.time.monotonic", return_value=started + 4.0):
        e1 = first._elapsed()
    with patch("opensquilla.cli.repl.stream.time.monotonic", return_value=started + 5.0):
        e2 = second._elapsed()
    assert e2 >= e1


class _RecordingLive:
    """Recorder for Rich Live constructions inside the renderer."""

    instances: list["_RecordingLive"] = []

    def __init__(self, renderable=None, **kwargs):
        self.renderable = renderable
        self.kwargs = kwargs
        self.updates: list[dict] = []
        self.started = 0
        self.stopped = 0
        _RecordingLive.instances.append(self)

    def start(self) -> None:
        self.started += 1

    def stop(self) -> None:
        self.stopped += 1

    def update(self, renderable, *, refresh: bool = False) -> None:
        self.renderable = renderable
        self.updates.append({"refresh": refresh})


@pytest.fixture
def recording_live(monkeypatch):
    _RecordingLive.instances = []
    monkeypatch.setattr("opensquilla.cli.repl.stream.Live", _RecordingLive)
    yield _RecordingLive
    _RecordingLive.instances = []


def test_only_waiting_live_is_constructed(recording_live) -> None:
    """Lock down: token streaming must not start a second Rich ``Live``.

    The historical Markdown+Panel Live update loop produced ghost panel
    borders on Windows PowerShell once the panel grew taller than the
    terminal viewport (especially with CJK content). The fix replaces it
    with plain-text writes plus a one-shot final Markdown panel. A second
    Live during streaming is the regression signal we guard against here.
    """
    with StreamingRenderer() as renderer:
        renderer.append_text("foo")
        renderer.append_text("bar")
        renderer.pulse()

    # Exactly one Live — the transient waiting indicator. No main Live
    # is created during the streaming phase any more.
    assert len(recording_live.instances) == 1, (
        f"expected only the waiting Live, got {len(recording_live.instances)}"
    )
    waiting_live = recording_live.instances[0]
    assert waiting_live.kwargs.get("transient") is True
    # Waiting indicator keeps auto-refresh so the elapsed-seconds counter
    # animates without external ticks.
    assert waiting_live.kwargs.get("auto_refresh", True) is not False
    # First append_text stops the waiting indicator before any text writes.
    assert waiting_live.stopped == 1
    assert waiting_live.updates == []


def test_append_text_writes_plain_to_console_stream(monkeypatch) -> None:
    """Deltas land verbatim on ``console.file`` — no Rich markup processing.

    Model output regularly contains ``[bracket]`` sequences that Rich would
    otherwise parse as markup tags. Routing the stream through
    ``console.file.write`` keeps the bytes untouched and bypasses the Live
    repaint path that previously caused the ghost-panel regression.
    """
    buf = io.StringIO()
    test_console = Console(file=buf, force_terminal=False, width=120, highlight=False)
    monkeypatch.setattr(stream_module, "console", test_console)
    monkeypatch.setattr(stream_module, "Live", _RecordingLive)
    _RecordingLive.instances = []

    with StreamingRenderer() as renderer:
        renderer.append_text("hello ")
        renderer.append_text("[not-markup] ")
        renderer.append_text("world")

    output = buf.getvalue()
    # Bracketed text reaches the terminal verbatim — it was never run
    # through Rich's markup parser.
    assert "[not-markup]" in output
    assert "hello " in output
    assert "world" in output
    assert renderer.buffer == "hello [not-markup] world"


def test_finalize_does_not_re_render_response_as_panel(monkeypatch) -> None:
    """The streamed text is the final view — no post-stream Markdown panel.

    Re-rendering the response after streaming produced a duplicated answer
    in the terminal (plain text once, panel once). Standard agent CLIs
    (Claude Code, codex, aider) leave the streamed output as the final
    view; we match that convention so the user reads the answer exactly
    once.
    """
    captured: list[object] = []

    def fake_print(*args, **kwargs) -> None:
        captured.extend(args)

    monkeypatch.setattr(stream_module, "Live", _RecordingLive)
    _RecordingLive.instances = []
    monkeypatch.setattr(stream_module.console, "print", fake_print)
    monkeypatch.setattr(stream_module.console, "file", io.StringIO(), raising=False)

    with StreamingRenderer() as renderer:
        renderer.append_text("# heading\n\nbody with **markdown**\n\n| a | b |\n|---|---|\n| 1 | 2 |")
        renderer.finalize(usage=None)

    panels = [obj for obj in captured if isinstance(obj, Panel)]
    assert panels == [], (
        f"finalize must not print a Markdown re-render panel; got {len(panels)}"
    )
    # The dim footer (usage/elapsed) is still emitted as a plain string.
    assert any(isinstance(obj, str) and "0.0" in obj for obj in captured)


@pytest.mark.parametrize(
    ("hostile", "label"),
    [
        ("\x1b[2J\x1b[H", "CSI clear-screen + cursor-home"),
        ("\x1b]0;pwned\x07", "OSC 0 set-title (BEL terminator)"),
        ("\x1b]52;c;cGF5bG9hZA==\x1b\\", "OSC 52 clipboard write (ST terminator)"),
        ("\x1bPtmux;esc\x1b\\", "DCS programmable string"),
        ("\x1bc", "ESC c full terminal reset"),
        ("hello\rOVERWRITE", "CR line-overwrite"),
        ("ding\x07ding", "BEL"),
        ("back\x08space", "backspace"),
    ],
)
def test_append_text_strips_terminal_control_sequences(
    monkeypatch, hostile: str, label: str
) -> None:
    """Untrusted model deltas must not drive the terminal emulator."""
    buf = io.StringIO()
    test_console = Console(
        file=buf, force_terminal=False, width=120, highlight=False
    )
    monkeypatch.setattr(stream_module, "console", test_console)
    monkeypatch.setattr(stream_module, "Live", _RecordingLive)
    _RecordingLive.instances = []

    with StreamingRenderer() as renderer:
        renderer.append_text(hostile)

    output = buf.getvalue()
    # No ESC byte and no surviving C0 control besides newline/tab can reach
    # the terminal — those are the bytes that would drive cursor/colour/
    # clipboard/title behaviour.
    assert "\x1b" not in output, f"ESC leaked for {label}: {output!r}"
    assert "\r" not in output
    assert "\x07" not in output
    assert "\x08" not in output
    # The renderer's in-memory buffer (used as TurnResult.text and the
    # source of the final Markdown panel) must mirror the same scrubbing
    # so /save and the post-stream panel re-render are equally safe.
    assert "\x1b" not in renderer.buffer
    assert "\r" not in renderer.buffer


def test_append_text_keeps_newlines_and_tabs(monkeypatch) -> None:
    """Sanitization must not destroy Markdown's structural whitespace."""
    buf = io.StringIO()
    test_console = Console(
        file=buf, force_terminal=False, width=120, highlight=False
    )
    monkeypatch.setattr(stream_module, "console", test_console)
    monkeypatch.setattr(stream_module, "Live", _RecordingLive)
    _RecordingLive.instances = []

    payload = "# heading\n\n- item one\n- item two\n\tindented"
    with StreamingRenderer() as renderer:
        renderer.append_text(payload)

    assert renderer.buffer == payload
    assert "# heading" in buf.getvalue()
    assert "\tindented" in buf.getvalue()


def _usage(turn_cost: float = 0.5) -> UsageSummary:
    return UsageSummary(
        input_tokens=10,
        output_tokens=20,
        cost_usd=turn_cost,
        model="deepseek/v4-flash",
    )


def test_footer_omits_cumulative_segment_when_no_total() -> None:
    """Backward-compat: no cumulative_cost → footer matches the pre-upgrade form."""
    renderer = StreamingRenderer()
    line = renderer.footer(_usage(turn_cost=0.123456), elapsed=1.0)
    assert "$0.123456" in line
    assert "∑" not in line, "cumulative segment must be suppressed when source is absent"


def test_footer_appends_session_total_with_sigma() -> None:
    """Gateway path: pass a session total → footer adds `(∑$X)` after turn cost."""
    renderer = StreamingRenderer()
    line = renderer.footer(_usage(turn_cost=0.123456), elapsed=1.0, cumulative_cost=2.789012)
    assert "$0.123456 (∑$2.789012)" in line, line


def test_footer_drops_cumulative_when_zero_or_negative() -> None:
    """A 0 cumulative is treated as 'no useful data' — keeps ∑ semantics clean."""
    renderer = StreamingRenderer()
    zero_line = renderer.footer(_usage(turn_cost=0.5), elapsed=1.0, cumulative_cost=0.0)
    negative_line = renderer.footer(_usage(turn_cost=0.5), elapsed=1.0, cumulative_cost=-0.01)
    assert "∑" not in zero_line
    assert "∑" not in negative_line


def test_footer_skips_cumulative_when_turn_cost_zero() -> None:
    """Free-tier turns don't render a turn-cost segment, so ∑ has no anchor either."""
    renderer = StreamingRenderer()
    line = renderer.footer(_usage(turn_cost=0.0), elapsed=1.0, cumulative_cost=2.5)
    assert "$" not in line, line
    assert "∑" not in line
