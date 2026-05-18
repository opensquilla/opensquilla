from __future__ import annotations

import asyncio
import json
import os
import shlex
import sys
import time
from dataclasses import dataclass

import pytest
import structlog.testing

from opensquilla.tools.builtin import shell
from opensquilla.tools.types import CallerKind, ToolContext, ToolError, current_tool_context


class _FakeStdin:
    def __init__(self) -> None:
        self.closed = False
        self.writes: list[bytes] = []

    def is_closing(self) -> bool:
        return self.closed

    def write(self, data: bytes) -> None:
        self.writes.append(data)

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None


@dataclass
class _FakeProcess:
    returncode: int | None = None
    stdin: _FakeStdin | None = None

    def __post_init__(self) -> None:
        if self.stdin is None:
            self.stdin = _FakeStdin()


def _ctx(
    session_key: str,
    *,
    is_owner: bool = False,
    agent_id: str = "agent",
    caller_kind: CallerKind = CallerKind.AGENT,
) -> ToolContext:
    return ToolContext(
        is_owner=is_owner,
        caller_kind=caller_kind,
        session_key=session_key,
        agent_id=agent_id,
    )


@pytest.fixture(autouse=True)
def _reset_bg_sessions():
    previous = dict(shell._bg_sessions)
    shell._bg_sessions.clear()
    yield
    shell._bg_sessions.clear()
    shell._bg_sessions.update(previous)


def _session(
    session_id: str,
    session_key: str | None,
    *,
    agent_id: str | None = "agent",
    done: bool = False,
    command: str | None = None,
    local_urls: list[str] | None = None,
) -> shell._BgSession:
    return shell._BgSession(
        session_id=session_id,
        command=command or f"cmd {session_id}",
        process=_FakeProcess(returncode=0 if done else None),  # type: ignore[arg-type]
        session_key=session_key,
        agent_id=agent_id,
        done=done,
        returncode=0 if done else None,
        local_urls=local_urls or [],
    )


def test_background_process_result_surfaces_local_http_server_url() -> None:
    session = _session(
        "server",
        "agent:main:one",
        command="cd /workspace && python3 -m http.server 8080",
        local_urls=shell._local_server_urls_from_command(
            "cd /workspace && python3 -m http.server 8080"
        ),
    )

    result = shell._background_process_result(session)

    assert "local_urls:" in result
    assert "- http://127.0.0.1:8080/" in result
    assert "include the local URL" in result


@pytest.mark.skipif(os.name != "posix", reason="process group behavior is POSIX-specific")
@pytest.mark.asyncio
async def test_exec_command_returns_when_shell_exits_even_if_descendant_holds_pipe() -> None:
    child_script = "import time; time.sleep(5)"
    parent_script = (
        "import subprocess, sys; "
        "subprocess.Popen([sys.executable, '-c', "
        f"{child_script!r}], stdout=sys.stdout, stderr=sys.stderr)"
    )
    command = f"{shlex.quote(sys.executable)} -c {shlex.quote(parent_script)}"

    started = time.monotonic()
    result = await shell.exec_command(command, timeout=1.0)
    elapsed = time.monotonic() - started

    assert result.startswith("exit_code=0\n")
    assert elapsed < 1.0


@pytest.mark.skipif(os.name != "posix", reason="process group behavior is POSIX-specific")
@pytest.mark.asyncio
async def test_exec_command_cleans_descendant_after_shell_exits(tmp_path) -> None:
    marker = tmp_path / "descendant-ran"
    child_script = (
        "import pathlib, time; "
        f"time.sleep(0.5); pathlib.Path({str(marker)!r}).write_text('ran')"
    )
    parent_script = (
        "import subprocess, sys; "
        "subprocess.Popen([sys.executable, '-c', "
        f"{child_script!r}])"
    )
    command = f"{shlex.quote(sys.executable)} -c {shlex.quote(parent_script)}"

    result = await shell.exec_command(command, timeout=1.0)
    await asyncio.sleep(0.8)

    assert result.startswith("exit_code=0\n")
    assert not marker.exists()


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "posix", reason="POSIX shell quoting is required")
async def test_exec_command_timeout_still_stops_foreground_process() -> None:
    command = f"{shlex.quote(sys.executable)} -c {shlex.quote('import time; time.sleep(5)')}"

    started = time.monotonic()
    result = await shell.exec_command(command, timeout=0.1)
    elapsed = time.monotonic() - started

    assert "[timeout after 0.1s]" in result
    assert elapsed < 1.0


@pytest.mark.asyncio
async def test_process_list_filters_to_current_session_and_warns_for_untagged() -> None:
    shell._bg_sessions["own"] = _session("own", "agent:main:one")
    shell._bg_sessions["other"] = _session("other", "agent:main:two")
    shell._bg_sessions["legacy"] = _session("legacy", None)

    token = current_tool_context.set(_ctx("agent:main:one"))
    try:
        with structlog.testing.capture_logs() as captured:
            payload = json.loads(await shell.process("list"))
    finally:
        current_tool_context.reset(token)

    assert [session["session_id"] for session in payload["sessions"]] == ["own"]
    assert any(event["event"] == "shell.bg_session_untagged" for event in captured)


@pytest.mark.asyncio
async def test_process_owner_context_can_list_all_sessions() -> None:
    shell._bg_sessions["own"] = _session("own", "agent:main:one")
    shell._bg_sessions["other"] = _session("other", "agent:main:two")

    token = current_tool_context.set(
        _ctx("agent:main:ops", is_owner=True, caller_kind=CallerKind.CLI)
    )
    try:
        payload = json.loads(await shell.process("list"))
    finally:
        current_tool_context.reset(token)

    assert {session["session_id"] for session in payload["sessions"]} == {"own", "other"}


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["poll", "log", "kill", "remove", "write", "submit", "eof"])
async def test_process_cross_context_operations_are_denied(action: str) -> None:
    shell._bg_sessions["owned-by-other"] = _session(
        "owned-by-other",
        "agent:main:other",
        done=action == "remove",
    )

    token = current_tool_context.set(_ctx("agent:main:one"))
    kwargs = {"data": "hello"} if action in {"write", "submit"} else {}
    try:
        with pytest.raises(ToolError, match="not accessible"):
            await shell.process(action, session_id="owned-by-other", **kwargs)
    finally:
        current_tool_context.reset(token)


@pytest.mark.asyncio
async def test_process_owner_context_can_poll_other_sessions() -> None:
    shell._bg_sessions["other"] = _session("other", "agent:main:two")

    token = current_tool_context.set(
        _ctx("agent:main:ops", is_owner=True, caller_kind=CallerKind.CLI)
    )
    try:
        payload = json.loads(await shell.process("poll", session_id="other"))
    finally:
        current_tool_context.reset(token)

    assert payload["status"] == "ok"
    assert payload["session"]["session_id"] == "other"


@pytest.mark.asyncio
async def test_process_poll_includes_local_urls_for_server_sessions() -> None:
    shell._bg_sessions["server"] = _session(
        "server",
        "agent:main:one",
        command="python -m http.server 9090",
        local_urls=["http://127.0.0.1:9090/"],
    )

    token = current_tool_context.set(_ctx("agent:main:one"))
    try:
        payload = json.loads(await shell.process("poll", session_id="server"))
    finally:
        current_tool_context.reset(token)

    assert payload["session"]["local_urls"] == ["http://127.0.0.1:9090/"]


@pytest.mark.asyncio
async def test_process_subagent_owner_context_is_not_admin_bypass() -> None:
    shell._bg_sessions["own"] = _session("own", "subagent:agent:main:one")
    shell._bg_sessions["other"] = _session("other", "agent:main:two")

    token = current_tool_context.set(
        _ctx("subagent:agent:main:one", is_owner=True, caller_kind=CallerKind.SUBAGENT)
    )
    try:
        payload = json.loads(await shell.process("list"))
        with pytest.raises(ToolError, match="not accessible"):
            await shell.process("poll", session_id="other")
    finally:
        current_tool_context.reset(token)

    assert [session["session_id"] for session in payload["sessions"]] == ["own"]
