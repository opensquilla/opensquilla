"""Streaming helpers for the live Textual surface."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from opensquilla.cli.tui.textual.app import TextualChatApp


@asynccontextmanager
async def textual_stream_output(
    app: TextualChatApp,
) -> AsyncIterator[Callable[[str], None]]:
    chunks: list[str] = []

    def write(payload: str) -> None:
        chunks.append(payload)

    try:
        yield write
    finally:
        if chunks:
            app.append_output("".join(chunks))
