from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import Any

import pytest

from opensquilla.cli.tui.opentui.messages import (
    CompletionContext,
    HostCompletionRequest,
    HostInputCancel,
    HostInputEof,
    HostInputSubmit,
    RouterPluginState,
    ScrollbackWrite,
)
from opensquilla.cli.tui.opentui.surface import (
    OpenTuiOutputHandle,
    OpenTuiSurface,
    open_opentui_surface,
)
from opensquilla.engine.commands import Surface


class FakeOpenTuiBridge:
    def __init__(self) -> None:
        self.messages: asyncio.Queue[object] = asyncio.Queue()
        self.sent: list[tuple[str, dict[str, Any] | None]] = []

    async def send(self, message_type: str, payload: object | None = None) -> None:
        if payload is None:
            self.sent.append((message_type, None))
            return
        self.sent.append(
            (message_type, payload if isinstance(payload, dict) else asdict(payload))
        )

    async def next_message(self) -> object | None:
        return await self.messages.get()

    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_opentui_surface_returns_submitted_lines_and_eof() -> None:
    bridge = FakeOpenTuiBridge()
    surface = OpenTuiSurface(bridge, approval_surface=Surface.CLI_GATEWAY)

    bridge.messages.put_nowait(HostInputSubmit(text="中文 prompt"))
    assert await surface.next_line() == "中文 prompt"

    bridge.messages.put_nowait(HostInputEof())
    assert await surface.next_line() is None


@pytest.mark.asyncio
async def test_opentui_surface_delegates_cancel_and_keeps_waiting() -> None:
    bridge = FakeOpenTuiBridge()
    surface = OpenTuiSurface(bridge, approval_surface=Surface.CLI_GATEWAY)
    cancelled: list[str] = []

    surface.set_cancel_callback(lambda: cancelled.append("cancel"))
    bridge.messages.put_nowait(HostInputCancel())
    bridge.messages.put_nowait(HostInputSubmit(text="after cancel"))

    assert await surface.next_line() == "after cancel"
    assert cancelled == ["cancel"]


@pytest.mark.asyncio
async def test_opentui_output_handle_writes_to_scrollback() -> None:
    bridge = FakeOpenTuiBridge()
    output = OpenTuiOutputHandle(bridge, approval_surface=Surface.CLI_GATEWAY)

    await output.write_through("tool output\nfinal answer")

    assert bridge.sent == [
        (
            "scrollback.write",
            asdict(ScrollbackWrite(text="tool output\nfinal answer")),
        )
    ]


@pytest.mark.asyncio
async def test_open_opentui_surface_sends_completion_context_on_startup() -> None:
    bridge = FakeOpenTuiBridge()

    async with open_opentui_surface(
        surface=Surface.CLI_GATEWAY,
        ready_marker="",
        print_ready_marker=False,
        bridge=bridge,
        completion_context=CompletionContext(catalog=(), files=()),
    ):
        pass

    assert bridge.sent == [
        (
            "composer.set",
            {
                "placeholder": "send a message",
                "text": "",
                "disabled": False,
            },
        ),
        (
            "completion.context",
            {
                "catalog": (),
                "files": (),
                "filters_sensitive_paths": True,
            },
        ),
    ]


@pytest.mark.asyncio
async def test_open_opentui_surface_marks_ready_after_completion_context() -> None:
    bridge = FakeOpenTuiBridge()

    async with open_opentui_surface(
        surface=Surface.CLI_GATEWAY,
        ready_marker="READY",
        bridge=bridge,
        completion_context=CompletionContext(catalog=(), files=()),
    ):
        pass

    assert [message_type for message_type, _payload in bridge.sent] == [
        "composer.set",
        "completion.context",
        "scrollback.write",
    ]
    assert bridge.sent[-1] == (
        "scrollback.write",
        asdict(ScrollbackWrite(text="READY\n")),
    )


@pytest.mark.asyncio
async def test_opentui_surface_answers_file_completion_without_returning_input(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from opensquilla.cli.tui.opentui import surface as surface_module

    calls: list[tuple[object, str, int]] = []

    def fake_enumerate_workspace_files(root, *, query: str, max_results: int):
        calls.append((root, query, max_results))
        return ["foo.py", "src/foo_bar.py"]

    monkeypatch.setattr(
        surface_module,
        "enumerate_workspace_files",
        fake_enumerate_workspace_files,
    )
    bridge = FakeOpenTuiBridge()
    surface = OpenTuiSurface(
        bridge,
        approval_surface=Surface.CLI_GATEWAY,
        workspace_dir=tmp_path,
    )

    bridge.messages.put_nowait(
        HostCompletionRequest(kind="file", query="foo", request_id=7)
    )
    bridge.messages.put_nowait(HostInputSubmit(text="hello"))

    assert await surface.next_line() == "hello"
    assert calls == [(tmp_path, "foo", 50)]
    assert bridge.sent == [
        (
            "completion.response",
            {
                "request_id": 7,
                "kind": "file",
                "items": [
                    {
                        "label": "foo.py",
                        "description": "foo.py",
                        "insert_text": "@foo.py ",
                        "category": "file",
                    },
                    {
                        "label": "src/foo_bar.py",
                        "description": "src/foo_bar.py",
                        "insert_text": "@src/foo_bar.py ",
                        "category": "file",
                    },
                ],
            },
        )
    ]


@pytest.mark.asyncio
async def test_opentui_surface_answers_file_completion_with_empty_items_without_workspace() -> None:
    bridge = FakeOpenTuiBridge()
    surface = OpenTuiSurface(bridge, approval_surface=Surface.CLI_GATEWAY)

    bridge.messages.put_nowait(HostCompletionRequest(kind="file", query="foo", request_id=8))
    bridge.messages.put_nowait(HostInputSubmit(text="after completion"))

    assert await surface.next_line() == "after completion"
    assert bridge.sent == [
        (
            "completion.response",
            {
                "request_id": 8,
                "kind": "file",
                "items": [],
            },
        )
    ]


@pytest.mark.asyncio
async def test_open_opentui_surface_uses_explicit_workspace_for_completion_context(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from opensquilla.cli.tui.opentui import surface as surface_module

    bridge = FakeOpenTuiBridge()
    captured: dict[str, Any] = {}

    def fake_build_completion_context(
        surface: Surface,
        *,
        workspace_dir,
    ) -> CompletionContext:
        captured["surface"] = surface
        captured["workspace_dir"] = workspace_dir
        return CompletionContext(catalog=(), files=("src/main.py",))

    monkeypatch.setenv("OPENSQUILLA_WORKSPACE_DIR", "/tmp/wrong-env-workspace")
    monkeypatch.setattr(
        surface_module,
        "build_completion_context",
        fake_build_completion_context,
    )

    async with open_opentui_surface(
        surface=Surface.CLI_STANDALONE,
        ready_marker="",
        print_ready_marker=False,
        bridge=bridge,
        workspace_dir=tmp_path,
    ):
        pass

    assert captured == {
        "surface": Surface.CLI_STANDALONE,
        "workspace_dir": tmp_path,
    }
    assert bridge.sent[-1] == (
        "completion.context",
        {
            "catalog": (),
            "files": ("src/main.py",),
            "filters_sensitive_paths": True,
        },
    )


def test_opentui_output_toolbar_invalidates_router_plugin() -> None:
    bridge = FakeOpenTuiBridge()
    output = OpenTuiOutputHandle(bridge, approval_surface=Surface.CLI_GATEWAY)

    output.set_toolbar("router_hud", "route standard -> fake-terminal 99% save 42%")
    output.set_toolbar("router_hud_style", "normal")
    output.set_toolbar("router_baseline_model", "vendor/big-model")
    output.set_toolbar("router_source", "router")
    output.set_toolbar("router_routing_applied", True)
    output.set_toolbar("router_rollout_phase", "full")
    output.invalidate()

    assert bridge.sent == [
        (
            "router.update",
            asdict(
                RouterPluginState(
                    model="fake-terminal",
                    route="standard 99%",
                    saving="42%",
                    context="-",
                    style="normal",
                    baseline_model="vendor/big-model",
                    source="router",
                    routing_applied=True,
                    rollout_phase="full",
                )
            ),
        )
    ]


def test_router_plugin_state_carries_observe_source_and_usage() -> None:
    bridge = FakeOpenTuiBridge()
    output = OpenTuiOutputHandle(bridge, approval_surface=Surface.CLI_GATEWAY)

    output.set_toolbar("router_hud", "observe standard -> fake-terminal 80%")
    output.set_toolbar("router_hud_style", "dim")
    output.set_toolbar("router_source", "observe")
    output.set_toolbar("router_routing_applied", False)
    output.set_toolbar("router_rollout_phase", "observe")
    output.set_toolbar("router_usage", "1.2k/856")
    output.invalidate()

    (_, payload) = bridge.sent[0]
    assert payload["source"] == "observe"
    assert payload["routing_applied"] is False
    assert payload["rollout_phase"] == "observe"
    assert payload["context"] == "1.2k/856"


def test_router_plugin_state_formats_cumulative_context_usage_percent() -> None:
    bridge = FakeOpenTuiBridge()
    output = OpenTuiOutputHandle(bridge, approval_surface=Surface.CLI_GATEWAY)

    output.set_toolbar("router_hud", "observe standard -> fake-terminal 80%")
    output.set_toolbar("router_hud_style", "dim")
    output.set_toolbar("router_usage", "1/2")
    output.set_toolbar("router_session_input", 84_000)
    output.set_toolbar("router_context_window", 200_000)
    output.invalidate()

    (_, payload) = bridge.sent[0]
    assert payload["context"] == "42% · 1/2"


@pytest.mark.parametrize(
    ("session_input", "context_window"),
    [
        (None, 200_000),
        (84_000, None),
    ],
)
def test_router_plugin_state_falls_back_to_turn_usage_without_context_data(
    session_input: int | None,
    context_window: int | None,
) -> None:
    bridge = FakeOpenTuiBridge()
    output = OpenTuiOutputHandle(bridge, approval_surface=Surface.CLI_GATEWAY)

    output.set_toolbar("router_hud", "observe standard -> fake-terminal 80%")
    output.set_toolbar("router_hud_style", "dim")
    output.set_toolbar("router_usage", "1/2")
    output.set_toolbar("router_session_input", session_input)
    output.set_toolbar("router_context_window", context_window)
    output.invalidate()

    (_, payload) = bridge.sent[0]
    assert payload["context"] == "1/2"


def test_router_plugin_state_context_stays_pending_without_usage() -> None:
    bridge = FakeOpenTuiBridge()
    output = OpenTuiOutputHandle(bridge, approval_surface=Surface.CLI_GATEWAY)

    output.set_toolbar("router_session_input", 84_000)
    output.set_toolbar("router_context_window", 200_000)
    output.invalidate()

    (_, payload) = bridge.sent[0]
    assert payload["context"] == "-"


def test_router_plugin_state_clamps_context_usage_percent() -> None:
    bridge = FakeOpenTuiBridge()
    output = OpenTuiOutputHandle(bridge, approval_surface=Surface.CLI_GATEWAY)

    output.set_toolbar("router_hud", "observe standard -> fake-terminal 80%")
    output.set_toolbar("router_hud_style", "dim")
    output.set_toolbar("router_usage", "1.2k/856")
    output.set_toolbar("router_session_input", 250_000)
    output.set_toolbar("router_context_window", 200_000)
    output.invalidate()

    (_, payload) = bridge.sent[0]
    assert payload["context"] == "100% · 1.2k/856"


def test_router_plugin_state_fallback_keeps_defaults_and_usage() -> None:
    bridge = FakeOpenTuiBridge()
    output = OpenTuiOutputHandle(bridge, approval_surface=Surface.CLI_GATEWAY)

    output.set_toolbar("router_hud", "fallback -> fake-terminal")
    output.set_toolbar("router_hud_style", "warning")
    output.set_toolbar("router_source", "fallback")
    output.set_toolbar("router_usage", "856/12")
    output.invalidate()

    (_, payload) = bridge.sent[0]
    assert payload["model"] == "fake-terminal"
    assert payload["route"] == "fallback"
    assert payload["source"] == "fallback"
    assert payload["context"] == "856/12"
    assert payload["style"] == "warning"


def test_router_plugin_state_pending_defaults_without_usage() -> None:
    bridge = FakeOpenTuiBridge()
    output = OpenTuiOutputHandle(bridge, approval_surface=Surface.CLI_GATEWAY)

    output.invalidate()

    (_, payload) = bridge.sent[0]
    assert payload["model"] == "pending"
    assert payload["route"] == "pending"
    assert payload["context"] == "-"
    assert payload["baseline_model"] == ""
    assert payload["routing_applied"] is True
    assert payload["rollout_phase"] == "full"


@pytest.mark.asyncio
async def test_output_handle_send_message_forwards_to_bridge() -> None:
    bridge = FakeOpenTuiBridge()
    output = OpenTuiOutputHandle(bridge, approval_surface=Surface.CLI_GATEWAY)

    await output.send_message("turn.begin", {"id": "t1"})
    await output.send_message("model.text", {"text": "hi"})

    assert bridge.sent == [
        ("turn.begin", {"id": "t1"}),
        ("model.text", {"text": "hi"}),
    ]
