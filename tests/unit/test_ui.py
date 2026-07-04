from __future__ import annotations

import sys
from io import BytesIO, TextIOWrapper

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


def test_dynamic_stream_replaces_unencodable_text_for_legacy_gbk_stream(
    monkeypatch,
) -> None:
    raw = BytesIO()
    stream = TextIOWrapper(raw, encoding="cp936", errors="strict")
    monkeypatch.setattr(sys, "stdout", stream)

    assert _DynamicStream("stdout").write("中文 🦐") == len("中文 🦐")
    stream.flush()

    assert raw.getvalue().decode("cp936") == "中文 ?"
