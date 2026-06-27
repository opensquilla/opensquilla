from __future__ import annotations

import sys

from opensquilla.ui import _DynamicStream


def test_dynamic_stream_write_returns_length_when_wrapped_stream_returns_none(
    monkeypatch,
) -> None:
    class NullStyleStream:
        def __init__(self) -> None:
            self.writes: list[str] = []

        def write(self, data: str) -> None:
            self.writes.append(data)
            return None

    stream = NullStyleStream()
    monkeypatch.setattr(sys, "stdout", stream)

    assert _DynamicStream("stdout").write("sample payload") == len("sample payload")
    assert stream.writes == ["sample payload"]
