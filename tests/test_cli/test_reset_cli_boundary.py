"""Boundary tests for the top-level reset CLI command."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest
import typer


def _tree_for(module: object) -> ast.Module:
    file_path = Path(str(module.__file__))
    return ast.parse(file_path.read_text(encoding="utf-8"))


def _function_def(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} not found")


def _body_name_ids(function: ast.FunctionDef) -> set[str]:
    return {
        node.id
        for statement in function.body
        for node in ast.walk(statement)
        if isinstance(node, ast.Name)
    }


def _body_call_names(function: ast.FunctionDef) -> set[str]:
    calls: set[str] = set()
    for statement in function.body:
        for node in ast.walk(statement):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name):
                calls.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                calls.add(node.func.attr)
    return calls


def test_reset_cmd_delegates_workflow_without_inline_gateway_or_rendering() -> None:
    """The Typer command body is a declaration boundary, not the reset workflow."""

    from opensquilla.cli import main, reset_workflows

    main_tree = _tree_for(main)
    workflow_tree = _tree_for(reset_workflows)
    reset_cmd = _function_def(main_tree, "reset_cmd")
    body_names = _body_name_ids(reset_cmd)
    body_calls = _body_call_names(reset_cmd)
    workflow_names = {
        node.id for node in ast.walk(workflow_tree) if isinstance(node, ast.Name)
    }

    assert "reset_session_for_cli" in body_calls
    assert "reset_session_for_cli" in {
        node.name
        for node in ast.walk(workflow_tree)
        if isinstance(node, ast.FunctionDef)
    }
    assert body_names.isdisjoint(
        {
            "GatewayClient",
            "GatewayRPCError",
            "normalize_gateway_url",
            "asyncio",
        }
    )
    assert body_calls.isdisjoint({"echo", "secho", "Exit"})
    assert not any(
        isinstance(node, ast.AsyncFunctionDef)
        for statement in reset_cmd.body
        for node in ast.walk(statement)
    )
    assert {"GatewayClient", "GatewayRPCError", "normalize_gateway_url", "asyncio"} <= (
        workflow_names
    )


def test_reset_workflow_normalizes_gateway_and_emits_success(monkeypatch) -> None:
    """The workflow owns client setup, RPC invocation, close, and presenter handoff."""

    from opensquilla.cli import reset_workflows

    events: list[tuple[str, Any]] = []
    result = {
        "previous_session_id": "old",
        "session_id": "new",
        "flush_receipt": {"mode": "skipped"},
    }

    class FakeGatewayClient:
        async def connect(self, url: str) -> None:
            events.append(("connect", url))

        async def reset_session(self, key: str) -> dict[str, Any]:
            events.append(("reset", key))
            return result

        async def close(self) -> None:
            events.append(("close", None))

    def fake_normalize(url: str) -> str:
        events.append(("normalize", url))
        return "ws://normalized/ws"

    def fake_emit_success(payload: dict[str, Any]) -> None:
        events.append(("success", payload))

    monkeypatch.setattr(reset_workflows, "GatewayClient", FakeGatewayClient)
    monkeypatch.setattr(reset_workflows, "normalize_gateway_url", fake_normalize)
    monkeypatch.setattr(reset_workflows, "emit_reset_success", fake_emit_success)

    reset_workflows.reset_session_for_cli("abc", gateway_url="http://gateway")

    assert events == [
        ("normalize", "http://gateway"),
        ("connect", "ws://normalized/ws"),
        ("reset", "abc"),
        ("close", None),
        ("success", result),
    ]


def test_reset_workflow_hands_rpc_failures_to_presenter(monkeypatch) -> None:
    """RPC failures stay behavior-compatible while moving out of main.py."""

    from opensquilla.cli import reset_workflows
    from opensquilla.cli.gateway_client import GatewayRPCError

    events: list[tuple[str, Any]] = []
    error = GatewayRPCError(
        "sessions.reset",
        code="FLUSH_FAILED",
        message="disk full",
        data={"session_id": "s-1", "flush_receipt": {"error": "no space"}},
    )

    class FakeGatewayClient:
        async def connect(self, url: str) -> None:
            events.append(("connect", url))

        async def reset_session(self, key: str) -> dict[str, Any]:
            events.append(("reset", key))
            raise error

        async def close(self) -> None:
            events.append(("close", None))

    def fake_emit_error_exit(exc: GatewayRPCError) -> None:
        events.append(("error", exc))
        raise typer.Exit(1)

    monkeypatch.setattr(reset_workflows, "GatewayClient", FakeGatewayClient)
    monkeypatch.setattr(reset_workflows, "normalize_gateway_url", lambda url: "ws://x/ws")
    monkeypatch.setattr(reset_workflows, "emit_reset_error_exit", fake_emit_error_exit)

    with pytest.raises(typer.Exit) as raised:
        reset_workflows.reset_session_for_cli("abc", gateway_url="http://gateway")

    assert raised.value.exit_code == 1
    assert events == [
        ("connect", "ws://x/ws"),
        ("reset", "abc"),
        ("close", None),
        ("error", error),
    ]


@pytest.mark.parametrize(
    ("receipt", "expected_lines"),
    [
        (
            {"mode": "llm", "duration_ms": 1234, "flushed_paths": ["/tmp/a.md"]},
            [
                "✓ Session reset (old → new).",
                "  Flush mode: llm (1.2s)",
                "  Saved to: /tmp/a.md",
            ],
        ),
        (
            {
                "mode": "raw",
                "duration_ms": 4567,
                "raw_reason": "timeout",
                "flushed_paths": ["/tmp/raw.json"],
            },
            [
                "✓ Session reset (old → new).",
                "  Flush mode: raw (reason: timeout, after 4.6s)",
                "  Saved to: /tmp/raw.json (raw transcript dump)",
            ],
        ),
        (
            {"mode": "skipped"},
            [
                "✓ Session reset (old → new).",
                "  Flush mode: skipped (empty transcript)",
            ],
        ),
        (
            {"mode": "custom"},
            ["✓ Session reset (old → new).", "  Flush mode: custom"],
        ),
    ],
)
def test_reset_presenter_emits_exact_success_text(
    receipt: dict[str, Any], expected_lines: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    from opensquilla.cli.reset_presenters import emit_reset_success

    emit_reset_success(
        {
            "previous_session_id": "old",
            "session_id": "new",
            "flush_receipt": receipt,
        }
    )

    assert capsys.readouterr().out.splitlines() == expected_lines


def test_reset_presenter_emits_exact_rpc_failure_text_and_exit(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from opensquilla.cli.gateway_client import GatewayRPCError
    from opensquilla.cli.reset_presenters import emit_reset_error_exit

    error = GatewayRPCError(
        "sessions.reset",
        message="flush service unavailable",
        data={"session_id": "s-1", "flush_receipt": {"error": "disk no"}},
    )

    with pytest.raises(typer.Exit) as raised:
        emit_reset_error_exit(error)

    assert raised.value.exit_code == 1
    assert capsys.readouterr().out.splitlines() == [
        "✗ Reset aborted: flush service unavailable",
        "  Session preserved: s-1",
        "  Cause: disk no",
    ]
