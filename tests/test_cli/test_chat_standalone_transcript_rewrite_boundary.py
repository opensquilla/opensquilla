"""Boundary tests for standalone chat transcript rewrite guards."""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from opensquilla.cli import chat_standalone_transcript_rewrite as transcript_rewrite


class _CaptureConsole:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def print(self, message: str) -> None:
        self.messages.append(message)


def test_module_boundary_exists_without_importing_chat_cmd() -> None:
    assert transcript_rewrite.__name__.endswith("chat_standalone_transcript_rewrite")
    module_path = Path(transcript_rewrite.__file__ or "")
    assert module_path.name == "chat_standalone_transcript_rewrite.py"
    source_tree = ast.parse(module_path.read_text())
    imported_modules = {
        alias.name
        for node in ast.walk(source_tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module
        for node in ast.walk(source_tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert "opensquilla.cli.chat_cmd" not in imported_modules


@pytest.mark.asyncio
async def test_read_standalone_transcript_awaits_async_get_transcript() -> None:
    class SessionManager:
        async def get_transcript(self, session_key: str) -> list[object]:
            assert session_key == "standalone:test"
            return [SimpleNamespace(role="user", content="hello")]

    transcript = await transcript_rewrite.read_standalone_transcript(
        SessionManager(),
        "standalone:test",
    )

    assert transcript == [SimpleNamespace(role="user", content="hello")]


@pytest.mark.asyncio
async def test_read_standalone_transcript_returns_empty_without_session_manager() -> None:
    assert (
        await transcript_rewrite.read_standalone_transcript(
            None,
            "standalone:test",
        )
        == []
    )


@pytest.mark.asyncio
async def test_read_standalone_transcript_falls_back_to_read_transcript() -> None:
    class SessionManager:
        def read_transcript(self, session_key: str) -> list[object]:
            assert session_key == "standalone:test"
            return [SimpleNamespace(role="assistant", content="reply")]

    transcript = await transcript_rewrite.read_standalone_transcript(
        SessionManager(),
        "standalone:test",
    )

    assert transcript == [SimpleNamespace(role="assistant", content="reply")]


@pytest.mark.asyncio
async def test_read_standalone_transcript_returns_empty_for_key_error() -> None:
    class SessionManager:
        def get_transcript(self, session_key: str) -> list[object]:
            raise KeyError(session_key)

    assert (
        await transcript_rewrite.read_standalone_transcript(
            SessionManager(),
            "standalone:test",
        )
        == []
    )


@pytest.mark.asyncio
async def test_read_standalone_transcript_returns_none_without_reader() -> None:
    assert (
        await transcript_rewrite.read_standalone_transcript(
            SimpleNamespace(),
            "standalone:test",
        )
        is None
    )


@pytest.mark.asyncio
async def test_read_standalone_transcript_returns_none_for_read_exception() -> None:
    class SessionManager:
        def get_transcript(self, session_key: str) -> list[object]:
            raise RuntimeError("read failed")

    assert (
        await transcript_rewrite.read_standalone_transcript(
            SessionManager(),
            "standalone:test",
        )
        is None
    )


@pytest.mark.asyncio
async def test_flush_before_standalone_rewrite_returns_true_for_empty_transcript() -> None:
    class SessionManager:
        async def get_transcript(self, session_key: str) -> list[object]:
            return []

    svc = SimpleNamespace(session_manager=SessionManager(), flush_service=None)

    assert (
        await transcript_rewrite.flush_before_standalone_rewrite(
            svc,
            "standalone:test",
            operation="Reset",
        )
        is True
    )


@pytest.mark.asyncio
async def test_flush_before_standalone_rewrite_fails_closed_without_flush_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture = _CaptureConsole()
    monkeypatch.setattr(transcript_rewrite, "console", capture)
    svc = SimpleNamespace(
        session_manager=SimpleNamespace(
            get_transcript=lambda session_key: [
                SimpleNamespace(role="user", content="persisted")
            ]
        ),
        flush_service=None,
    )

    result = await transcript_rewrite.flush_before_standalone_rewrite(
        svc,
        "standalone:test",
        operation="Reset",
    )

    assert result is False
    assert capture.messages == [
        "[yellow]Reset aborted: flush service is unavailable and "
        "the durable transcript is non-empty.[/yellow]"
    ]


@pytest.mark.asyncio
async def test_flush_before_standalone_rewrite_executes_flush_with_exact_kwargs() -> None:
    transcript = [SimpleNamespace(role="user", content="persisted")]

    class FlushService:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        async def execute(
            self,
            flushed_transcript: object,
            session_key: str,
            **kwargs: Any,
        ) -> object:
            self.calls.append(
                {
                    "transcript": flushed_transcript,
                    "session_key": session_key,
                    "kwargs": kwargs,
                }
            )
            return SimpleNamespace(mode="llm", error=None)

    flush_service = FlushService()
    svc = SimpleNamespace(
        session_manager=SimpleNamespace(get_transcript=lambda session_key: transcript),
        flush_service=flush_service,
    )

    result = await transcript_rewrite.flush_before_standalone_rewrite(
        svc,
        "standalone:test",
        operation="Compact",
    )

    assert result is True
    assert flush_service.calls == [
        {
            "transcript": transcript,
            "session_key": "standalone:test",
            "kwargs": {
                "agent_id": "main",
                "timeout": 30.0,
                "message_window": 0,
                "segment_mode": "auto",
            },
        }
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("flush_service", "expected_warning"),
    [
        pytest.param(
            "exception",
            "[yellow]Compact aborted: flush failed (provider down).[/yellow]",
        ),
        pytest.param(
            "error_receipt",
            "[yellow]Compact aborted: flush failed (provider down).[/yellow]",
        ),
    ],
)
async def test_flush_before_standalone_rewrite_fails_closed_for_flush_errors(
    monkeypatch: pytest.MonkeyPatch,
    flush_service: str,
    expected_warning: str,
) -> None:
    class ExceptionFlushService:
        async def execute(self, *args: object, **kwargs: object) -> object:
            raise RuntimeError("provider down")

    class ErrorReceiptFlushService:
        async def execute(self, *args: object, **kwargs: object) -> object:
            return SimpleNamespace(mode="error", error="provider down")

    flush_services = {
        "exception": ExceptionFlushService(),
        "error_receipt": ErrorReceiptFlushService(),
    }
    capture = _CaptureConsole()
    monkeypatch.setattr(transcript_rewrite, "console", capture)
    svc = SimpleNamespace(
        session_manager=SimpleNamespace(
            get_transcript=lambda session_key: [
                SimpleNamespace(role="user", content="persisted")
            ]
        ),
        flush_service=flush_services[flush_service],
    )

    result = await transcript_rewrite.flush_before_standalone_rewrite(
        svc,
        "standalone:test",
        operation="Compact",
    )

    assert result is False
    assert capture.messages == [expected_warning]
