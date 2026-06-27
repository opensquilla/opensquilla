from __future__ import annotations

import pytest

from opensquilla.cli.tui.native.renderer import NativeStreamRenderer


class _RecordingOutputHandle:
    approval_surface = object()

    def __init__(self) -> None:
        self.writes: list[str] = []

    async def write_through(self, payload: str) -> None:
        self.writes.append(payload)

    def stream_output(self):
        raise AssertionError("native renderer writes through directly")


@pytest.mark.asyncio
async def test_native_renderer_writes_answer_text_to_terminal_output() -> None:
    output = _RecordingOutputHandle()
    renderer = NativeStreamRenderer(output_handle=output)

    renderer.__enter__()
    await renderer.aappend_text("hello", presentation="answer")
    await renderer.aappend_text(" there", presentation="answer")
    await renderer.afinalize(None)

    assert renderer.buffer == "hello there"
    assert output.writes == ["hello", " there", "\n"]
