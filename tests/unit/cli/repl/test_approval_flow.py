"""Approval flow extraction tests for the TUI boundary."""

from __future__ import annotations

import asyncio
from io import StringIO

import pytest
from rich.console import Console

from opensquilla.engine.commands import Surface


class _FakeLive:
    def __init__(self) -> None:
        self.stop_calls = 0
        self.start_calls = 0

    def stop(self) -> None:
        self.stop_calls += 1

    def start(self) -> None:
        self.start_calls += 1


def test_maybe_handle_approval_flips_bypass_and_resolves_allow_always(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.cli.repl import approval as approval_mod

    calls: list[tuple[str, bool, bool]] = []
    elevated_state: dict[str, str | None] = {"mode": None}

    async def _resolver(approval_id: str, approved: bool, *, allow_always: bool = False) -> None:
        calls.append((approval_id, approved, allow_always))

    async def _fake_prompt_approval(prefix: str, *, surface: Surface) -> str:
        assert prefix == "Decision [o/a/b/d]: "
        assert surface is Surface.CLI_GATEWAY
        return "b"

    monkeypatch.setattr(approval_mod, "prompt_approval", _fake_prompt_approval)

    live = _FakeLive()
    result = asyncio.run(
        approval_mod.maybe_handle_approval(
            {
                "status": "approval_required",
                "approval_id": "approval-123",
                "command": "rm -rf /tmp/thing",
                "warning": "Needs approval",
            },
            live,
            _resolver,
            elevated_state=elevated_state,
            surface=Surface.CLI_GATEWAY,
        )
    )

    assert result is None
    assert live.stop_calls == 1
    assert live.start_calls == 1
    assert calls == [("approval-123", True, True)]
    assert elevated_state["mode"] == "bypass"


def test_maybe_handle_approval_blocked_notice_does_not_resolve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.cli.repl import approval as approval_mod

    buffer = StringIO()
    monkeypatch.setattr(
        approval_mod,
        "console",
        Console(file=buffer, force_terminal=False, width=100, highlight=False),
    )
    calls: list[str] = []

    async def _resolver(approval_id: str, approved: bool, *, allow_always: bool = False) -> None:
        del approved, allow_always
        calls.append(approval_id)

    live = _FakeLive()

    asyncio.run(
        approval_mod.maybe_handle_approval(
            {
                "status": "blocked",
                "command": "cat /private/token",
                "message": "Sensitive path is blocked.",
            },
            live,
            _resolver,
        )
    )

    assert live.stop_calls == 1
    assert live.start_calls == 1
    assert calls == []
    assert "Sensitive path is blocked." in buffer.getvalue()


@pytest.mark.parametrize(
    ("answer", "expected_approved", "expected_allow_always", "expected_mode"),
    [
        ("a", True, True, None),
        ("d", False, False, None),
    ],
)
def test_maybe_handle_approval_maps_prompt_decisions_without_bypass(
    monkeypatch: pytest.MonkeyPatch,
    answer: str,
    expected_approved: bool,
    expected_allow_always: bool,
    expected_mode: str | None,
) -> None:
    from opensquilla.cli.repl import approval as approval_mod

    calls: list[tuple[str, bool, bool]] = []
    elevated_state: dict[str, str | None] = {"mode": None}

    async def _resolver(approval_id: str, approved: bool, *, allow_always: bool = False) -> None:
        calls.append((approval_id, approved, allow_always))

    async def _fake_prompt_approval(_prefix: str, *, surface: Surface) -> str:
        assert surface is Surface.CLI_STANDALONE
        return answer

    monkeypatch.setattr(approval_mod, "prompt_approval", _fake_prompt_approval)

    live = _FakeLive()

    asyncio.run(
        approval_mod.maybe_handle_approval(
            {
                "status": "approval_required",
                "approval_id": "approval-456",
                "command": "rm artifact",
                "warning": "Needs approval",
            },
            live,
            _resolver,
            elevated_state=elevated_state,
            surface=Surface.CLI_STANDALONE,
        )
    )

    assert live.stop_calls == 1
    assert live.start_calls == 1
    assert calls == [("approval-456", expected_approved, expected_allow_always)]
    assert elevated_state["mode"] == expected_mode


def test_maybe_handle_approval_restarts_live_after_resolver_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.cli.repl import approval as approval_mod

    buffer = StringIO()
    monkeypatch.setattr(
        approval_mod,
        "console",
        Console(file=buffer, force_terminal=False, width=100, highlight=False),
    )

    async def _fake_prompt_approval(_prefix: str, *, surface: Surface) -> str:
        assert surface is Surface.CLI_GATEWAY
        return "o"

    async def _resolver(
        _approval_id: str,
        _approved: bool,
        *,
        allow_always: bool = False,
    ) -> None:
        del allow_always
        raise RuntimeError("resolver unavailable")

    monkeypatch.setattr(approval_mod, "prompt_approval", _fake_prompt_approval)

    live = _FakeLive()

    asyncio.run(
        approval_mod.maybe_handle_approval(
            {
                "status": "approval_pending",
                "approval_id": "approval-789",
                "command": "rm artifact",
                "message": "Waiting for approval.",
            },
            live,
            _resolver,
        )
    )

    assert live.stop_calls == 1
    assert live.start_calls == 1
    assert "Failed to resolve approval" in buffer.getvalue()
