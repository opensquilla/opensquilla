from __future__ import annotations

import sys
from io import BytesIO, TextIOWrapper

import typer

from opensquilla.cli.stdio import configure_stdio_for_unicode


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
