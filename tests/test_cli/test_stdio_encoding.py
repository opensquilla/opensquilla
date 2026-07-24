from __future__ import annotations

import json
import sys
from io import BytesIO, TextIOWrapper

import typer

from opensquilla.cli.agent_cmd import _event_to_jsonl
from opensquilla.cli.stdio import configure_stdio_for_unicode
from opensquilla.engine.types import TextDeltaEvent


def test_configure_stdio_for_unicode_allows_typer_echo_on_gbk_stream(
    monkeypatch,
) -> None:
    raw = BytesIO()
    stream = TextIOWrapper(raw, encoding="cp936", errors="strict")
    monkeypatch.setattr(sys, "stdout", stream)

    configure_stdio_for_unicode()
    typer.echo("hello 🦐")
    stream.flush()

    assert raw.getvalue().decode("utf-8").strip() == "hello 🦐"


def test_configure_stdio_for_unicode_keeps_stderr_event_jsonl_utf8(
    monkeypatch,
) -> None:
    raw = BytesIO()
    stream = TextIOWrapper(raw, encoding="cp1252", errors="backslashreplace")
    monkeypatch.setattr(sys, "stderr", stream)

    configure_stdio_for_unicode()
    line = _event_to_jsonl(TextDeltaEvent(text="你好🙂"))
    assert line is not None
    print(line, file=sys.stderr, flush=True)

    payload = json.loads(raw.getvalue().decode("utf-8"))
    assert payload == {
        "_event": True,
        "kind": "text_delta",
        "text": "你好🙂",
        "presentation": "answer",
    }
