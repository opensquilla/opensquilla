from __future__ import annotations

import inspect
from typing import Any

import pytest


def test_terminal_renderer_wraps_streaming_renderer(monkeypatch) -> None:
    created: list[dict[str, Any]] = []
    output_handle = object()

    class _FakeStreamingRenderer:
        def __init__(self, **kwargs: Any) -> None:
            created.append(kwargs)
            self.buffer = "raw-buffer"

        def __enter__(self) -> _FakeStreamingRenderer:
            return self

        def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
            return False

    monkeypatch.setattr(
        "opensquilla.cli.repl.terminal_renderer.StreamingRenderer",
        _FakeStreamingRenderer,
    )

    from opensquilla.cli.repl.terminal_renderer import TerminalRenderer

    renderer = TerminalRenderer(title="assistant", output_handle=output_handle)

    assert renderer.raw_renderer is not None
    assert renderer.output_handle is output_handle
    assert created == [{"title": "assistant", "output_handle": output_handle}]


def test_terminal_renderer_exposes_turn_stream_renderer_contract(monkeypatch) -> None:
    calls: list[str] = []

    class _FakeStreamingRenderer:
        buffer = "answer"

        def __init__(self, **_kwargs: Any) -> None:
            return None

        def __enter__(self) -> _FakeStreamingRenderer:
            calls.append("enter")
            return self

        def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
            calls.append("exit")
            return False

        def pulse(self) -> None:
            calls.append("pulse")

        def stop(self) -> None:
            calls.append("stop")

        def start(self) -> None:
            calls.append("start")

    monkeypatch.setattr(
        "opensquilla.cli.repl.terminal_renderer.StreamingRenderer",
        _FakeStreamingRenderer,
    )

    from opensquilla.cli.repl.terminal_renderer import TerminalRenderer

    renderer = TerminalRenderer()

    with renderer as active:
        assert active is renderer
        assert renderer.buffer == "answer"
        renderer.pulse()
        renderer.stop()
        renderer.start()

    assert calls == ["enter", "pulse", "stop", "start", "exit"]


async def test_terminal_renderer_fails_fast_when_wrapped_renderer_misses_method(
    monkeypatch,
) -> None:
    class _IncompleteStreamingRenderer:
        def __init__(self, **_kwargs: Any) -> None:
            return None

    monkeypatch.setattr(
        "opensquilla.cli.repl.terminal_renderer.StreamingRenderer",
        _IncompleteStreamingRenderer,
    )

    from opensquilla.cli.repl.terminal_renderer import TerminalRenderer

    renderer = TerminalRenderer()

    with pytest.raises(AttributeError, match="aappend_text.*append_text"):
        await renderer.aappend_text("lost")


def test_streaming_renderer_constructor_uses_output_handle_boundary() -> None:
    from opensquilla.cli.repl.stream import StreamingRenderer

    params = inspect.signature(StreamingRenderer).parameters

    assert "output_handle" in params
    assert "chat_app" not in params
