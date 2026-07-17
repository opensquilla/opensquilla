"""Behavioral coverage for the TUI slash adapters and shared helpers."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from opensquilla.cli.chat.session_state import ChatSessionState
from opensquilla.cli.chat.turn import TurnResult
from opensquilla.cli.tui.adapters import slash_bridge as _slash_bridge
from opensquilla.cli.tui.adapters import slash_gateway as _slash_gateway
from opensquilla.cli.tui.adapters import slash_standalone as _slash_standalone
from opensquilla.cli.tui.adapters.slash_common import (
    record_turn,
    registry_handler_words,
    resolve_transcript_target,
    transcript_messages_to_markdown,
)
from opensquilla.cli.tui.adapters.slash_gateway import (
    GATEWAY_SLASH_HANDLER_WORDS,
    GatewaySlashContext,
    handle_gateway_slash_command,
)
from opensquilla.cli.tui.adapters.slash_policy import SlashCategory, classify
from opensquilla.cli.tui.adapters.slash_standalone import (
    STANDALONE_SLASH_HANDLER_WORDS,
    StandaloneSlashContext,
    StandaloneSlashServices,
    handle_standalone_slash_command,
)
from opensquilla.engine.commands import Surface

# Exit words are intercepted by the runtime loops before slash dispatch, so
# neither handler chain owns them.
_RUNTIME_OWNED_WORDS = frozenset({"/exit", "/quit"})


class _RecordingConsole:
    def __init__(self) -> None:
        self.entries: list[Any] = []

    def print(self, *args: Any, **kwargs: Any) -> None:
        self.entries.append(args[0] if args else "")

    def text(self) -> str:
        return "\n".join(str(entry) for entry in self.entries)


def _fake_error_panel(message: str, *, title: str = "Error") -> str:
    return f"[panel:{title}] {message}"


def _patch_gateway_io(monkeypatch: pytest.MonkeyPatch) -> _RecordingConsole:
    recorder = _RecordingConsole()
    monkeypatch.setattr(_slash_gateway, "console", recorder)
    monkeypatch.setattr(_slash_gateway, "error_panel", _fake_error_panel)
    return recorder


def _patch_standalone_io(monkeypatch: pytest.MonkeyPatch) -> _RecordingConsole:
    recorder = _RecordingConsole()
    monkeypatch.setattr(_slash_standalone, "console", recorder)
    monkeypatch.setattr(_slash_standalone, "error_panel", _fake_error_panel)
    return recorder


class _StubGatewayClient:
    """Protocol-shaped double covering every method the adapter dispatches."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.created: list[dict[str, Any]] = []
        self.resolve_payloads: dict[str, dict[str, Any]] = {}
        self.history: list[dict[str, Any]] = []
        self.history_pages: dict[str | None, dict[str, Any]] = {}
        self.raise_map: dict[str, Exception] = {}
        self._counter = 0

    def _maybe_raise(self, method: str) -> None:
        exc = self.raise_map.get(method)
        if exc is not None:
            raise exc

    async def call(self, method: str, params: dict | None = None) -> Any:
        self.calls.append(("call", (method, params)))
        self._maybe_raise("call")
        if method == "meta.list":
            return {"skills": []}
        return {"ok": True}

    async def create_session(
        self,
        agent_id: str = "main",
        model: str | None = None,
        display_name: str | None = None,
    ) -> str:
        self._maybe_raise("create_session")
        self._counter += 1
        key = f"agent:main:test:{self._counter}"
        self.created.append({"key": key, "model": model, "display_name": display_name})
        return key

    async def list_sessions(self, limit: int = 50) -> dict[str, Any]:
        self._maybe_raise("list_sessions")
        return {"sessions": []}

    async def resolve_session(self, key: str) -> dict[str, Any]:
        self._maybe_raise("resolve_session")
        payload = self.resolve_payloads.get(key)
        if payload is not None:
            return dict(payload)
        return {"session_key": key, "model": None}

    async def delete_sessions(self, keys: list[str]) -> dict[str, Any]:
        self._maybe_raise("delete_sessions")
        self.calls.append(("delete_sessions", tuple(keys)))
        return {"deleted": list(keys), "errors": []}

    async def reset_session(self, key: str) -> dict[str, Any]:
        self._maybe_raise("reset_session")
        return {"reset": True, "key": key}

    async def compact_session(self, key: str) -> dict[str, Any]:
        self._maybe_raise("compact_session")
        return {"compacted": False}

    async def list_models(
        self,
        provider: str | None = None,
        capabilities: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        self._maybe_raise("list_models")
        return []

    async def patch_session(self, key: str, **fields: Any) -> dict[str, Any]:
        self._maybe_raise("patch_session")
        self.calls.append(("patch_session", (key, fields)))
        return {"ok": True}

    async def usage_status(self) -> dict[str, Any]:
        self._maybe_raise("usage_status")
        return {"totalTokens": 0, "totalCostUsd": 0.0}

    async def upload_file(self, path: Path, mime: str, name: str) -> str:
        return "file-1"

    def send_message(
        self,
        session_key: str,
        message: str,
        attachments: list[dict] | None = None,
        elevated: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        async def _events() -> AsyncIterator[dict[str, Any]]:
            yield {}

        return _events()

    async def resolve_approval(
        self,
        approval_id: str,
        approved: bool,
        *,
        choice: str | None = None,
    ) -> Any:
        return {"ok": True}

    async def abort_session(self, key: str) -> dict[str, Any]:
        return {"ok": True}

    async def session_history(
        self,
        session_key: str,
        limit: int = 1000,
        *,
        before: str | None = None,
        after: str | None = None,
        include_canonical: bool | None = None,
        include_summaries: bool | None = None,
    ) -> dict[str, Any]:
        self._maybe_raise("session_history")
        self.calls.append(
            (
                "session_history",
                {
                    "session_key": session_key,
                    "limit": limit,
                    "before": before,
                    "after": after,
                    "include_canonical": include_canonical,
                    "include_summaries": include_summaries,
                },
            )
        )
        if self.history_pages:
            return dict(self.history_pages[before])
        return {"messages": list(self.history), "has_more": False}

    async def forget_approvals(self, target: str | None = None) -> dict[str, Any]:
        self.calls.append(("forget_approvals", target))
        return {"ok": True}

    async def approvals_snapshot(self) -> dict[str, Any]:
        return {"mode": "prompt"}

    async def set_approval_mode(self, mode: str) -> dict[str, Any]:
        self.calls.append(("set_approval_mode", mode))
        return {"ok": True}


def _gateway_context(
    client: _StubGatewayClient | None = None,
    *,
    model: str | None = "openai/test",
    requested_model: str | None = None,
) -> GatewaySlashContext:
    return GatewaySlashContext(
        state=ChatSessionState(session_key="agent:main:test:0", model=model),
        client=client or _StubGatewayClient(),
        elevated_state={"mode": None},
        requested_model=requested_model,
    )


class _StandaloneHarness:
    def __init__(self) -> None:
        self.transcripts: dict[str, list[Any]] = {}
        self.read_errors: dict[str, Exception] = {}

    async def create_session(self, session_key: str, *, agent_id: str = "main") -> object:
        return SimpleNamespace(session_key=session_key, agent_id=agent_id)

    async def read_transcript(self, session_key: str) -> list[Any]:
        exc = self.read_errors.get(session_key)
        if exc is not None:
            raise exc
        return list(self.transcripts.get(session_key, []))

    async def truncate_session(self, session_key: str, *, max_messages: int = 0) -> None:
        self.transcripts[session_key] = []

    async def compact_session(
        self,
        session_key: str,
        context_window_tokens: int,
        config: object | None = None,
    ) -> str:
        return "summary"

    async def flush_transcript(
        self,
        transcript: object,
        session_key: str,
        **kwargs: object,
    ) -> object:
        return SimpleNamespace(
            mode="llm",
            error=None,
            indexed_chunk_count=1,
            integrity_status="ok",
            output_coverage_status="ok",
            invalid_candidate_count=0,
            candidate_missing_ids=[],
            obligation_status="ok",
            obligation_missing_ids=[],
        )


def _standalone_context(
    harness: _StandaloneHarness | None = None,
    *,
    session_key: str = "agent:main:standalone:test",
    model: str | None = "openai/test",
) -> StandaloneSlashContext:
    harness = harness or _StandaloneHarness()
    state = ChatSessionState(session_key=session_key, model=model)
    return StandaloneSlashContext(
        state=state,
        session_key=session_key,
        model=model,
        tool_ctx=object(),
        slash_services=StandaloneSlashServices(
            create_session=harness.create_session,
            read_transcript=harness.read_transcript,
            truncate_session=harness.truncate_session,
            compact_session=harness.compact_session,
            flush_transcript=harness.flush_transcript,
        ),
        turn_runner=object(),
        build_tool_ctx=lambda _session_key: object(),
        replace_session=lambda **_updates: None,
    )


# --------------------------------------------------------------------------- #
# Word sets derive from the engine registry and the chains cover them          #
# --------------------------------------------------------------------------- #


def test_handler_word_sets_derive_from_engine_registry() -> None:
    assert GATEWAY_SLASH_HANDLER_WORDS == registry_handler_words(Surface.CLI_GATEWAY)
    assert STANDALONE_SLASH_HANDLER_WORDS == registry_handler_words(Surface.CLI_STANDALONE)
    assert "/meta" in GATEWAY_SLASH_HANDLER_WORDS
    assert "/usage" not in STANDALONE_SLASH_HANDLER_WORDS


async def test_gateway_handler_chain_covers_every_registry_word(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    _patch_gateway_io(monkeypatch)
    for word in sorted(GATEWAY_SLASH_HANDLER_WORDS - _RUNTIME_OWNED_WORDS):
        handled = await handle_gateway_slash_command(word, _gateway_context())
        assert handled is True, f"gateway handler chain does not dispatch {word}"


async def test_standalone_handler_chain_covers_every_registry_word(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    recorder = _patch_standalone_io(monkeypatch)
    for word in sorted(STANDALONE_SLASH_HANDLER_WORDS - _RUNTIME_OWNED_WORDS):
        recorder.entries.clear()
        handled = await handle_standalone_slash_command(word, _standalone_context())
        assert handled is True, f"standalone handler chain does not dispatch {word}"
        assert "Unknown command" not in recorder.text(), f"{word} fell through as unknown"


# --------------------------------------------------------------------------- #
# Twin return contracts                                                        #
# --------------------------------------------------------------------------- #


async def test_gateway_unknown_command_returns_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_gateway_io(monkeypatch)
    handled = await handle_gateway_slash_command("/definitely-unknown", _gateway_context())
    assert handled is False


async def test_standalone_unknown_command_prints_notice_and_returns_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _patch_standalone_io(monkeypatch)
    handled = await handle_standalone_slash_command("/definitely-unknown", _standalone_context())
    assert handled is True
    assert "Unknown command" in recorder.text()


# --------------------------------------------------------------------------- #
# Connection loss keeps the REPL alive                                         #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("cmd", "method"),
    [
        ("/sessions", "list_sessions"),
        ("/clear", "reset_session"),
        ("/usage", "usage_status"),
        ("/new", "create_session"),
    ],
)
async def test_gateway_connection_loss_renders_reconnect_hint(
    monkeypatch: pytest.MonkeyPatch,
    cmd: str,
    method: str,
) -> None:
    recorder = _patch_gateway_io(monkeypatch)
    client = _StubGatewayClient()
    client.raise_map[method] = ConnectionError(
        "Gateway connection lost; restart chat or reconnect before sending another command."
    )

    handled = await handle_gateway_slash_command(cmd, _gateway_context(client))

    assert handled is True
    output = recorder.text()
    assert "Gateway command failed" in output
    assert "Gateway connection lost" in output
    assert "opensquilla gateway" in output


async def test_gateway_os_error_from_rpc_is_reported_not_raised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _patch_gateway_io(monkeypatch)
    client = _StubGatewayClient()
    client.raise_map["list_models"] = OSError("socket closed")

    handled = await handle_gateway_slash_command("/models", _gateway_context(client))

    assert handled is True
    assert "socket closed" in recorder.text()


# --------------------------------------------------------------------------- #
# /save error mapping and durable precedence                                   #
# --------------------------------------------------------------------------- #


async def test_gateway_save_bad_path_renders_error_panel(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    recorder = _patch_gateway_io(monkeypatch)
    client = _StubGatewayClient()
    client.history = [{"role": "user", "text": "hello"}]
    target = tmp_path / "missing-dir" / "out.md"

    handled = await handle_gateway_slash_command(f"/save {target}", _gateway_context(client))

    assert handled is True
    assert "Could not save transcript" in recorder.text()
    assert not target.exists()


async def test_gateway_save_reads_all_canonical_history_pages(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_gateway_io(monkeypatch)
    client = _StubGatewayClient()
    client.history_pages = {
        None: {
            "messages": [
                {"message_id": "m3", "role": "user", "text": "later question"},
                {"message_id": "m4", "role": "assistant", "text": "later answer"},
            ],
            "has_more": True,
            "oldest_cursor": "3|3",
            "newest_cursor": "4|4",
        },
        "3|3": {
            "messages": [
                {"message_id": "m1", "role": "user", "text": "earliest question"},
                {"message_id": "m2", "role": "assistant", "text": "earliest answer"},
            ],
            "has_more": False,
            "oldest_cursor": "1|1",
            "newest_cursor": "2|2",
        },
    }
    target = tmp_path / "all-history.md"

    handled = await handle_gateway_slash_command(f"/save {target}", _gateway_context(client))

    assert handled is True
    saved = target.read_text(encoding="utf-8")
    assert saved.index("earliest question") < saved.index("later question")
    history_calls = [call for call in client.calls if call[0] == "session_history"]
    assert [call[1]["before"] for call in history_calls] == [None, "3|3"]
    assert all(call[1]["include_canonical"] is True for call in history_calls)
    assert all(call[1]["include_summaries"] is False for call in history_calls)


async def test_gateway_save_does_not_write_partial_file_when_cursor_stalls(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    recorder = _patch_gateway_io(monkeypatch)
    client = _StubGatewayClient()
    stalled_page = {
        "messages": [{"message_id": "m1", "role": "user", "text": "partial"}],
        "has_more": True,
        "oldest_cursor": "1|1",
        "newest_cursor": "1|1",
    }
    client.history_pages = {None: stalled_page, "1|1": stalled_page}
    target = tmp_path / "partial.md"

    handled = await handle_gateway_slash_command(f"/save {target}", _gateway_context(client))

    assert handled is True
    assert not target.exists()
    assert "cursor did not advance" in recorder.text()


async def test_standalone_save_bad_path_renders_error_panel(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    recorder = _patch_standalone_io(monkeypatch)
    context = _standalone_context()
    context.state.transcript.add("user", "hello")
    target = tmp_path / "missing-dir" / "out.md"

    handled = await handle_standalone_slash_command(f"/save {target}", context)

    assert handled is True
    assert "Could not save transcript" in recorder.text()
    assert not target.exists()


async def test_standalone_save_exports_durable_history_after_resume(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    recorder = _patch_standalone_io(monkeypatch)
    harness = _StandaloneHarness()
    session_key = "agent:main:standalone:resumed"
    harness.transcripts[session_key] = [
        SimpleNamespace(role="user", content="persisted question"),
        SimpleNamespace(role="assistant", content="persisted answer"),
    ]
    context = _standalone_context(harness, session_key=session_key)
    target = tmp_path / "resumed.md"

    handled = await handle_standalone_slash_command(f"/save {target}", context)

    assert handled is True
    saved = target.read_text(encoding="utf-8")
    assert "persisted question" in saved
    assert "persisted answer" in saved
    assert "Saved transcript" in recorder.text()


async def test_standalone_save_falls_back_to_memory_when_durable_read_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_standalone_io(monkeypatch)
    harness = _StandaloneHarness()
    session_key = "agent:main:standalone:test"
    harness.read_errors[session_key] = RuntimeError("storage offline")
    context = _standalone_context(harness, session_key=session_key)
    context.state.transcript.add("user", "in-memory only")
    target = tmp_path / "fallback.md"

    handled = await handle_standalone_slash_command(f"/save {target}", context)

    assert handled is True
    assert "in-memory only" in target.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Requested-vs-routed model separation                                         #
# --------------------------------------------------------------------------- #


async def test_gateway_new_does_not_pin_routed_display_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_gateway_io(monkeypatch)
    client = _StubGatewayClient()
    # A router-default session: the stored session model is None even though
    # the display model shows the router's last pick.
    client.resolve_payloads["agent:main:test:0"] = {"model": None}
    context = _gateway_context(client, model="router/last-pick")

    handled = await handle_gateway_slash_command("/new", context)

    assert handled is True
    assert client.created[0]["model"] is None


async def test_gateway_new_prefers_explicit_requested_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_gateway_io(monkeypatch)
    client = _StubGatewayClient()
    context = _gateway_context(client, model="router/last-pick", requested_model="openai/explicit")

    await handle_gateway_slash_command("/new", context)

    assert client.created[0]["model"] == "openai/explicit"


async def test_gateway_new_requested_model_survives_pin_read_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An erroring resolve must never override an explicitly requested model."""
    recorder = _patch_gateway_io(monkeypatch)
    client = _StubGatewayClient()
    client.raise_map["resolve_session"] = RuntimeError("gateway busy")
    context = _gateway_context(client, model="router/last-pick", requested_model="openai/explicit")

    handled = await handle_gateway_slash_command("/new", context)

    assert handled is True
    assert client.created[0]["model"] == "openai/explicit"
    assert "Could not read" not in recorder.text()


async def test_gateway_new_inherits_stored_session_pin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_gateway_io(monkeypatch)
    client = _StubGatewayClient()
    client.resolve_payloads["agent:main:test:0"] = {"model": "openai/pinned"}
    context = _gateway_context(client, model="router/last-pick")

    await handle_gateway_slash_command("/new", context)

    assert client.created[0]["model"] == "openai/pinned"


async def test_gateway_new_warns_when_pin_read_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A slow/erroring resolve while creating a new session must not silently
    drop the pin: warn the user that the router default applies instead."""
    recorder = _patch_gateway_io(monkeypatch)
    client = _StubGatewayClient()
    client.raise_map["resolve_session"] = RuntimeError("gateway busy")
    context = _gateway_context(client, model="router/last-pick")

    handled = await handle_gateway_slash_command("/new", context)

    assert handled is True
    # No explicit pin could be read, so the new session is created unpinned...
    assert client.created[0]["model"] is None
    # ...but the user is told, rather than left assuming the pin carried over.
    output = recorder.text()
    assert "Could not read the current session's model pin" in output
    assert "/model" in output


async def test_gateway_model_records_explicit_request_on_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_gateway_io(monkeypatch)
    client = _StubGatewayClient()
    context = _gateway_context(client)

    handled = await handle_gateway_slash_command("/model openai/chosen", context)

    assert handled is True
    assert context.requested_model == "openai/chosen"
    assert context.state.model == "openai/chosen"
    assert ("patch_session", ("agent:main:test:0", {"model": "openai/chosen"})) in client.calls


# --------------------------------------------------------------------------- #
# /delete of the active session                                                #
# --------------------------------------------------------------------------- #


async def test_gateway_delete_active_session_switches_to_fresh_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _patch_gateway_io(monkeypatch)
    client = _StubGatewayClient()
    client.resolve_payloads["agent:main:test:0"] = {
        "session_key": "agent:main:test:0",
        "model": None,
    }
    context = _gateway_context(client)
    context.state.transcript.add("user", "hello")

    handled = await handle_gateway_slash_command("/delete agent:main:test:0", context)

    assert handled is True
    assert len(client.created) == 1
    assert context.state.session_key == client.created[0]["key"]
    assert context.state.transcript.turns == []
    assert "switched to a new session" in recorder.text()


async def test_gateway_delete_other_session_keeps_active_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _patch_gateway_io(monkeypatch)
    client = _StubGatewayClient()
    client.resolve_payloads["agent:main:other"] = {
        "session_key": "agent:main:other",
        "model": None,
    }
    context = _gateway_context(client)

    handled = await handle_gateway_slash_command("/delete agent:main:other", context)

    assert handled is True
    assert client.created == []
    assert context.state.session_key == "agent:main:test:0"
    assert "Deleted session" in recorder.text()


async def test_gateway_delete_active_session_refreshes_display_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deleting the active session must refresh state.model to the replacement
    session's pin, like /new does — not leave the deleted session's stale
    display model showing in /status and the HUD."""
    _patch_gateway_io(monkeypatch)
    client = _StubGatewayClient()
    client.resolve_payloads["agent:main:test:0"] = {
        "session_key": "agent:main:test:0",
        "model": "openai/replacement-pin",
    }
    # The replacement session (next created key) resolves to its own pin.
    client.resolve_payloads["agent:main:test:1"] = {"model": "openai/replacement-pin"}
    context = _gateway_context(client, model="openai/stale-display")

    handled = await handle_gateway_slash_command("/delete agent:main:test:0", context)

    assert handled is True
    assert client.created[0]["model"] == "openai/replacement-pin"
    assert context.state.model == "openai/replacement-pin"


async def test_gateway_delete_active_session_model_falls_back_on_resolve_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the post-create resolve fails, the display model still reflects the
    replacement pin rather than the deleted session's stale value."""
    _patch_gateway_io(monkeypatch)

    class _DeleteResolveOnceClient(_StubGatewayClient):
        def __init__(self) -> None:
            super().__init__()
            self._resolves = 0

        async def resolve_session(self, key: str) -> dict[str, Any]:
            self._resolves += 1
            # First resolve (the /delete target lookup) succeeds; the
            # post-create refresh resolve fails.
            if self._resolves >= 2:
                raise RuntimeError("gateway busy")
            return {"session_key": key, "model": "openai/replacement-pin"}

    client = _DeleteResolveOnceClient()
    context = _gateway_context(client, model="openai/stale-display")

    handled = await handle_gateway_slash_command("/delete agent:main:test:0", context)

    assert handled is True
    assert client.created[0]["model"] == "openai/replacement-pin"
    assert context.state.model == "openai/replacement-pin"


# --------------------------------------------------------------------------- #
# Destructive / exit classification matches dispatch                           #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("command", ["/clear", "  /clear  ", "/reset", "/compact", "/cmp"])
def test_classify_destructive_exact_bare_word(command: str) -> None:
    assert classify(command) is SlashCategory.DESTRUCTIVE


@pytest.mark.parametrize("command", ["/CLEAR", "/Clear", "/clear now", "/reset trailing-junk"])
def test_classify_never_purges_for_inputs_dispatch_rejects(command: str) -> None:
    category = classify(command)
    assert category is not SlashCategory.DESTRUCTIVE
    assert category is not SlashCategory.EXIT
    assert category is not SlashCategory.NON_SLASH


@pytest.mark.parametrize("command", ["/exit", "/quit", " /exit "])
def test_classify_exit_exact_bare_word(command: str) -> None:
    assert classify(command) is SlashCategory.EXIT


@pytest.mark.parametrize("command", ["/EXIT", "/exit now", "/Quit"])
def test_classify_exit_variants_enqueue_for_runtime_interception(command: str) -> None:
    category = classify(command)
    assert category is not SlashCategory.EXIT
    assert category is not SlashCategory.DESTRUCTIVE
    assert category is not SlashCategory.NON_SLASH


# --------------------------------------------------------------------------- #
# Protocol double works for approval-flavored commands                         #
# --------------------------------------------------------------------------- #


async def test_gateway_approval_commands_accept_protocol_double(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_gateway_io(monkeypatch)
    client = _StubGatewayClient()
    context = _gateway_context(client)

    assert await handle_gateway_slash_command("/approvals", context) is True
    assert await handle_gateway_slash_command("/forget some-target", context) is True
    assert await handle_gateway_slash_command("/permissions off", context) is True
    assert ("forget_approvals", "some-target") in client.calls
    assert ("set_approval_mode", "prompt") in client.calls
    assert context.state.elevated is None


def test_tool_compress_dead_code_is_removed() -> None:
    assert not hasattr(_slash_gateway, "_handle_tool_compress_command")
    assert not hasattr(_slash_bridge, "handle_tool_compress_command")


# --------------------------------------------------------------------------- #
# Shared helper behavior                                                       #
# --------------------------------------------------------------------------- #


def test_resolve_transcript_target_defaults_to_session_derived_name() -> None:
    target = resolve_transcript_target("/save", "agent:main:test:1")
    assert target == Path("opensquilla-chat-agent-main-test-1.md")
    explicit = resolve_transcript_target("/save /tmp/out.md", "agent:main:test:1")
    assert explicit == Path("/tmp/out.md")


def test_transcript_messages_to_markdown_accepts_dicts_and_rows() -> None:
    markdown = transcript_messages_to_markdown(
        [
            {"role": "user", "text": "dict question"},
            SimpleNamespace(role="assistant", content="row answer"),
        ]
    )
    assert "dict question" in markdown
    assert "row answer" in markdown


def test_record_turn_updates_transcript_and_usage() -> None:
    state = ChatSessionState(session_key="agent:main:test:2")
    record_turn(state, "ask", TurnResult(text="answer"))
    assert [turn.role for turn in state.transcript.turns] == ["user", "assistant"]
    assert state.transcript.turns[0].content == "ask"
    assert state.transcript.turns[1].content == "answer"
