"""Boundary tests for chat streaming presentation helpers."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
CHAT_CMD = ROOT / "src" / "opensquilla" / "cli" / "chat_cmd.py"
CHAT_STREAM_PRESENTERS = (
    ROOT / "src" / "opensquilla" / "cli" / "chat_stream_presenters.py"
)


def _module_tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} not found")


def _called_attributes(node: ast.AST) -> set[str]:
    calls: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
            calls.add(child.func.attr)
    return calls


def _called_names(node: ast.AST) -> set[str]:
    calls: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Name):
            calls.add(child.func.id)
    return calls


def test_chat_stream_presenter_module_defines_moved_helpers() -> None:
    tree = _module_tree(CHAT_STREAM_PRESENTERS)
    definitions = {
        node.name for node in tree.body if isinstance(node, ast.FunctionDef)
    }

    assert {
        "render_gateway_task_group_status",
        "artifact_event_payload",
        "artifact_status_line",
        "render_artifact_status",
    }.issubset(definitions)


def test_chat_cmd_imports_and_delegates_to_stream_presenters() -> None:
    tree = _module_tree(CHAT_CMD)
    imports_stream_presenter = any(
        isinstance(node, ast.ImportFrom)
        and node.module == "opensquilla.cli"
        and any(alias.name == "chat_stream_presenters" for alias in node.names)
        for node in tree.body
    )
    assert imports_stream_presenter

    expected_delegates = {
        "_render_gateway_task_group_status": "render_gateway_task_group_status",
        "_artifact_event_payload": "artifact_event_payload",
        "_artifact_status_line": "artifact_status_line",
    }
    for wrapper_name, presenter_call in expected_delegates.items():
        wrapper = _function(tree, wrapper_name)
        assert presenter_call in _called_attributes(wrapper)

    stream_gateway = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "_stream_response_gateway"
    )
    stream_turnrunner = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "_stream_response_turnrunner"
    )
    for stream_fn in (stream_gateway, stream_turnrunner):
        assert "_render_artifact_status" in _called_names(stream_fn)


def test_chat_cmd_stream_helpers_no_longer_own_formatting_branches() -> None:
    tree = _module_tree(CHAT_CMD)

    task_status_wrapper = _function(tree, "_render_gateway_task_group_status")
    task_status_source = ast.get_source_segment(
        CHAT_CMD.read_text(encoding="utf-8"), task_status_wrapper
    )
    assert task_status_source is not None
    assert "subagents waiting" not in task_status_source
    assert "synthesizing final answer" not in task_status_source
    assert "background synthesis" not in task_status_source

    artifact_payload_wrapper = _function(tree, "_artifact_event_payload")
    artifact_payload_source = ast.get_source_segment(
        CHAT_CMD.read_text(encoding="utf-8"), artifact_payload_wrapper
    )
    assert artifact_payload_source is not None
    assert "artifact_payload(" not in artifact_payload_source


def test_task_group_status_rendering_uses_callable_renderer_status() -> None:
    from opensquilla.cli import chat_stream_presenters

    renderer = SimpleNamespace(buffer="", statuses=[])

    def status(message: str, **kwargs: Any) -> None:
        renderer.statuses.append((message, kwargs))

    renderer.status = status

    chat_stream_presenters.render_gateway_task_group_status(
        "session.event.task_group.waiting",
        {"pending_count": 2},
        renderer,
    )
    chat_stream_presenters.render_gateway_task_group_status(
        "session.event.task_group.synthesizing",
        {"child_count": 3},
        renderer,
    )
    chat_stream_presenters.render_gateway_task_group_status(
        "session.event.task_group.done",
        {"delivery_status": "not_applicable"},
        renderer,
    )
    chat_stream_presenters.render_gateway_task_group_status(
        "session.event.task_group.failed",
        {"error_message": "child failed"},
        renderer,
    )

    assert renderer.buffer == ""
    assert renderer.statuses == [
        ("subagents waiting (2 pending)", {"style": "dim"}),
        (
            "subagents complete; synthesizing final answer from 3 children",
            {"style": "dim"},
        ),
        ("background synthesis complete (delivery: not_applicable)", {"style": "dim"}),
        ("background synthesis failed: child failed", {"style": "yellow"}),
    ]


def test_artifact_payload_sanitizes_gateway_event() -> None:
    from opensquilla.cli import chat_stream_presenters

    artifact = chat_stream_presenters.artifact_event_payload(
        {
            "event": "session.event.artifact",
            "id": "art-chat",
            "kind": "artifact_ref",
            "name": "report.txt",
            "mime": "text/plain",
            "size": 4,
            "sha256": "e" * 64,
            "session_id": "session-1",
            "session_key": "agent:main:abc123",
            "sessionKey": "agent:main:abc123",
            "source": "publish_artifact",
            "created_at": "2026-05-06T12:00:00Z",
            "download_url": "/api/v1/artifacts/art-chat?sessionKey=agent%3Amain%3Aabc123",
        }
    )

    assert artifact["download_url"] == "/api/v1/artifacts/art-chat"
    assert "session_key" not in artifact
    assert "sessionKey" not in json.dumps(artifact)


def test_artifact_status_falls_back_to_console_when_renderer_has_no_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.cli import chat_stream_presenters

    printed: list[str] = []
    monkeypatch.setattr(
        chat_stream_presenters,
        "console",
        SimpleNamespace(print=lambda message: printed.append(message)),
    )

    chat_stream_presenters.render_artifact_status(
        {"id": "art-chat", "name": "report.txt", "download_url": "/api/v1/artifacts/art-chat"},
        renderer=SimpleNamespace(buffer="answer"),
    )

    assert printed == ["Generated file: report.txt -> /api/v1/artifacts/art-chat"]
