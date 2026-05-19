"""Boundary tests for standalone chat approval prompt handling."""

from __future__ import annotations

import ast
import json
from io import StringIO
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console

from opensquilla.cli import chat_approval_prompts

ROOT = Path(__file__).resolve().parents[2]
APPROVAL_PROMPTS = ROOT / "src" / "opensquilla" / "cli" / "chat_approval_prompts.py"


class _FakeLive:
    def __init__(self) -> None:
        self.events: list[str] = []

    def stop(self) -> None:
        self.events.append("stop")

    def start(self) -> None:
        self.events.append("start")


@pytest.fixture
def approval_console(monkeypatch: pytest.MonkeyPatch) -> StringIO:
    buffer = StringIO()
    monkeypatch.setattr(
        chat_approval_prompts,
        "console",
        Console(file=buffer, force_terminal=False, width=100, highlight=False),
    )
    return buffer


def test_module_boundary_exists_without_chat_cmd_import() -> None:
    tree = ast.parse(APPROVAL_PROMPTS.read_text(encoding="utf-8"))
    imports_chat_cmd = any(
        (
            isinstance(node, ast.Import)
            and any(alias.name == "opensquilla.cli.chat_cmd" for alias in node.names)
        )
        or (
            isinstance(node, ast.ImportFrom)
            and node.module in {"opensquilla.cli.chat_cmd", "opensquilla.cli"}
            and any(alias.name == "chat_cmd" for alias in node.names)
        )
        for node in ast.walk(tree)
    )

    assert hasattr(chat_approval_prompts, "maybe_handle_approval")
    assert hasattr(chat_approval_prompts, "local_approval_resolver")
    assert not imports_chat_cmd


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "payload"),
    [
        (
            "approval_pending",
            json.dumps(
                {
                    "status": "approval_pending",
                    "approval_id": "pid-1",
                    "command": "rm secret",
                    "message": "Waiting for approval.",
                }
            ),
        ),
        (
            "approval_required",
            {
                "status": "approval_required",
                "approval_id": "pid-2",
                "command": "rm secret",
                "warning": "Destructive command",
            },
        ),
    ],
)
async def test_pending_and_required_approval_prompt_and_resolve_once(
    monkeypatch: pytest.MonkeyPatch,
    approval_console: StringIO,
    status: str,
    payload: str | dict[str, Any],
) -> None:
    live = _FakeLive()
    calls: list[tuple[str, bool, bool]] = []

    async def _prompt(_: str) -> str:
        return "o"

    monkeypatch.setattr(chat_approval_prompts, "prompt_approval", _prompt)

    async def resolver(approval_id: str, approved: bool, *, allow_always: bool = False) -> None:
        calls.append((approval_id, approved, allow_always))

    await chat_approval_prompts.maybe_handle_approval(payload, live, resolver)

    assert calls == [("pid-1" if status == "approval_pending" else "pid-2", True, False)]
    assert live.events == ["stop", "start"]
    assert (
        "Approval pending" if status == "approval_pending" else "Approval required"
    ) in approval_console.getvalue()


@pytest.mark.asyncio
async def test_bypass_updates_elevated_state_and_allows_always(
    monkeypatch: pytest.MonkeyPatch,
    approval_console: StringIO,
) -> None:
    live = _FakeLive()
    elevated_state: dict[str, str | None] = {"mode": None}
    calls: list[tuple[str, bool, bool]] = []

    async def _prompt(_: str) -> str:
        return "bypass"

    monkeypatch.setattr(chat_approval_prompts, "prompt_approval", _prompt)

    async def resolver(approval_id: str, approved: bool, *, allow_always: bool = False) -> None:
        calls.append((approval_id, approved, allow_always))

    await chat_approval_prompts.maybe_handle_approval(
        {
            "status": "approval_required",
            "approval_id": "pid-bypass",
            "command": "rm secret",
        },
        live,
        resolver,
        elevated_state=elevated_state,
    )

    assert calls == [("pid-bypass", True, True)]
    assert elevated_state == {"mode": "bypass"}
    assert "Approved + bypass mode" in approval_console.getvalue()
    assert "Sensitive paths still blocked" in approval_console.getvalue()


@pytest.mark.asyncio
async def test_blocked_payload_renders_without_resolver_call(approval_console: StringIO) -> None:
    live = _FakeLive()
    calls: list[tuple[str, bool, bool]] = []

    async def resolver(approval_id: str, approved: bool, *, allow_always: bool = False) -> None:
        calls.append((approval_id, approved, allow_always))

    await chat_approval_prompts.maybe_handle_approval(
        {
            "status": "blocked",
            "command": "rm -rf /private",
            "message": "Sensitive path blocked.",
        },
        live,
        resolver,
    )

    assert calls == []
    assert live.events == ["stop", "start"]
    assert "Blocked (sensitive path)" in approval_console.getvalue()
    assert "Sensitive path blocked." in approval_console.getvalue()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        None,
        42,
        "not json",
        "[]",
        {"status": "ok", "approval_id": "pid"},
        {"status": "approval_required", "approval_id": ""},
        {"status": "approval_pending", "approval_id": None},
    ],
)
async def test_invalid_and_non_approval_payloads_do_nothing(payload: object) -> None:
    live = _FakeLive()
    calls: list[tuple[str, bool, bool]] = []

    async def resolver(approval_id: str, approved: bool, *, allow_always: bool = False) -> None:
        calls.append((approval_id, approved, allow_always))

    await chat_approval_prompts.maybe_handle_approval(payload, live, resolver)

    assert calls == []
    assert live.events == []


@pytest.mark.asyncio
async def test_resolver_errors_are_reported_without_raising(
    monkeypatch: pytest.MonkeyPatch,
    approval_console: StringIO,
) -> None:
    live = _FakeLive()

    async def _prompt(_: str) -> str:
        return "always"

    monkeypatch.setattr(chat_approval_prompts, "prompt_approval", _prompt)

    async def resolver(
        approval_id: str, approved: bool, *, allow_always: bool = False
    ) -> None:
        raise RuntimeError(f"cannot resolve {approval_id}:{approved}:{allow_always}")

    await chat_approval_prompts.maybe_handle_approval(
        {
            "status": "approval_required",
            "approval_id": "pid-error",
            "command": "rm secret",
        },
        live,
        resolver,
    )

    assert "Failed to resolve approval:" in approval_console.getvalue()
    assert live.events == ["stop", "start"]


@pytest.mark.asyncio
async def test_local_approval_resolver_uses_application_approval_queue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, bool, bool]] = []

    class _Queue:
        def resolve(self, approval_id: str, approved: bool, *, allow_always: bool = False) -> None:
            calls.append((approval_id, approved, allow_always))

    monkeypatch.setattr(
        "opensquilla.application.approval_queue.get_approval_queue",
        lambda: _Queue(),
    )

    resolver = chat_approval_prompts.local_approval_resolver()
    await resolver("pid-local", True, allow_always=True)

    assert calls == [("pid-local", True, True)]
