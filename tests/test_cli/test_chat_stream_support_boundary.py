"""Boundary tests for chat stream support helpers."""

from __future__ import annotations

import ast
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
CHAT_CMD = ROOT / "src" / "opensquilla" / "cli" / "chat_cmd.py"
CHAT_STREAM_SUPPORT = ROOT / "src" / "opensquilla" / "cli" / "chat_stream_support.py"

MOVED_HELPERS = {
    "_turn_stream_error_message",
    "_timeout_exception_message",
    "_optional_positive_config_float",
    "_wrap_cli_turn_stream",
}


def _module_tree(path: Path) -> ast.Module:
    assert path.exists(), f"{path} does not exist"
    return ast.parse(path.read_text(encoding="utf-8"))


def _support_module() -> Any:
    assert CHAT_STREAM_SUPPORT.exists(), "chat stream support helpers were not extracted"
    return import_module("opensquilla.cli.chat_stream_support")


def test_chat_stream_support_module_defines_moved_helpers() -> None:
    tree = _module_tree(CHAT_STREAM_SUPPORT)
    definitions = {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
    }

    assert MOVED_HELPERS.issubset(definitions)


def test_chat_cmd_keeps_compat_aliases_without_owning_support_helpers() -> None:
    from opensquilla.cli import chat_cmd

    support = _support_module()
    tree = _module_tree(CHAT_CMD)
    chat_cmd_definitions = {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
    }

    assert MOVED_HELPERS.isdisjoint(chat_cmd_definitions)
    for helper_name in MOVED_HELPERS:
        assert getattr(chat_cmd, helper_name) is getattr(support, helper_name)


def test_turn_stream_error_message_preserves_timeout_terminal_reply() -> None:
    support = _support_module()

    iteration_timeout = SimpleNamespace(
        message="Iteration 1 exceeded iteration_timeout",
        code="iteration_timeout",
    )
    idle_timeout = SimpleNamespace(
        message="Stream idle for more than 60s",
        code="runtime_error",
    )
    normal_error = SimpleNamespace(message="regular failure", code="runtime_error")

    assert (
        support._turn_stream_error_message(iteration_timeout)
        == "The task timed out before it could finish."
    )
    assert (
        support._turn_stream_error_message(idle_timeout)
        == "The task timed out before it could finish."
    )
    assert support._turn_stream_error_message(normal_error) == "regular failure"


def test_timeout_exception_message_preserves_terminal_reply_text() -> None:
    support = _support_module()

    assert (
        support._timeout_exception_message(
            TimeoutError("Gateway task timeout: Stream idle for more than 60s")
        )
        == "The task timed out before it could finish."
    )


@pytest.mark.parametrize(
    ("raw", "default", "expected"),
    [
        ("2.5", 180.0, 2.5),
        (0, 180.0, None),
        (-1, 180.0, None),
        ("bad", 4.0, 4.0),
    ],
)
def test_optional_positive_config_float_handles_config_wrappers(
    raw: object,
    default: float,
    expected: float | None,
) -> None:
    support = _support_module()
    source = SimpleNamespace(config=SimpleNamespace(stream_value=raw))

    assert support._optional_positive_config_float(source, "stream_value", default) == expected


def test_wrap_cli_turn_stream_delegates_to_runtime_wrapper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    support = _support_module()
    captured: dict[str, Any] = {}
    source_stream = object()
    wrapped_stream = object()

    def fake_wrap_stream(stream: Any, **kwargs: Any) -> object:
        captured["stream"] = stream
        captured.update(kwargs)
        return wrapped_stream

    from opensquilla.runtime import stream_wrappers

    monkeypatch.setattr(stream_wrappers, "wrap_stream", fake_wrap_stream)

    config_source = SimpleNamespace(
        config=SimpleNamespace(
            agent_stream_idle_timeout_seconds="3.5",
            agent_stream_heartbeat_interval_seconds="0.25",
        )
    )

    assert support._wrap_cli_turn_stream(source_stream, config_source) is wrapped_stream
    assert captured == {
        "stream": source_stream,
        "idle_timeout": 3.5,
        "heartbeat_interval": 0.25,
        "heartbeat_phase": "cli",
        "heartbeat_message": "Still working",
    }
