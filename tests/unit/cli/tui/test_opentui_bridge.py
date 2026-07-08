from __future__ import annotations

import asyncio
import io
import json
import os
import sys
import threading

import pytest

from opensquilla.cli.tui import opentui as _opentui_pkg  # noqa: F401  (ensure package import)
from opensquilla.cli.tui.opentui import bridge as bridge_module
from opensquilla.cli.tui.opentui.bridge import (
    OpenTuiBridge,
    OpenTuiBridgeError,
    OpenTuiHostPaths,
    check_opentui_host_available,
)
from opensquilla.cli.tui.opentui.messages import (
    HostInputSubmit,
    HostToPythonMessageError,
    ScrollbackWrite,
)
from opensquilla.cli.tui.renderers.selection import RendererBackendAvailability


def test_missing_opentui_host_dependencies_report_install_command(tmp_path, monkeypatch) -> None:
    package_dir = tmp_path / "package"
    package_dir.mkdir()
    monkeypatch.setattr(bridge_module.os, "name", "posix")
    monkeypatch.setattr(bridge_module.shutil, "which", lambda cmd: f"/usr/bin/{cmd}")

    availability = check_opentui_host_available(package_dir=package_dir, runtime_bin="bun")

    assert availability.available is False
    assert availability.reason is not None
    assert "@opentui/core" in availability.reason
    assert f"bun install --cwd {package_dir}" in availability.reason


def test_opentui_host_reports_fd_bridge_unsupported_on_windows(tmp_path, monkeypatch) -> None:
    package_dir = tmp_path / "package"
    (package_dir / "node_modules" / "@opentui" / "core").mkdir(parents=True)
    (package_dir / "src").mkdir()
    (package_dir / "src" / "main.mjs").write_text("", encoding="utf-8")
    monkeypatch.setattr(bridge_module.os, "name", "nt")

    availability = check_opentui_host_available(package_dir=package_dir, runtime_bin="bun")

    assert availability.available is False
    assert availability.reason is not None
    assert "Windows" in availability.reason
    assert "file-descriptor" in availability.reason


async def _attach_exited_process(bridge: OpenTuiBridge, *, code: int, stderr: str) -> None:
    """Attach a real, already-spawned child that exits with ``code`` to the bridge."""
    script = f"import sys; sys.stderr.write({stderr!r}); sys.exit({code})"
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-c", script, stderr=asyncio.subprocess.PIPE
    )
    bridge._process = process
    bridge._stderr_task = asyncio.create_task(bridge._drain_stderr())
    bridge._from_host_file = io.StringIO("")  # read pipe is at EOF


@pytest.mark.asyncio
async def test_next_message_raises_with_stderr_when_host_crashes() -> None:
    bridge = OpenTuiBridge()
    await _attach_exited_process(bridge, code=3, stderr="fatal: boom\n")

    with pytest.raises(OpenTuiBridgeError) as exc_info:
        await bridge.next_message()

    message = str(exc_info.value)
    assert "code 3" in message
    assert "fatal: boom" in message


@pytest.mark.asyncio
async def test_next_message_returns_none_on_clean_host_exit() -> None:
    bridge = OpenTuiBridge()
    await _attach_exited_process(bridge, code=0, stderr="")

    assert await bridge.next_message() is None


@pytest.mark.asyncio
async def test_next_message_tolerates_invalid_utf8_and_skips_garbage() -> None:
    """A corrupted / non-JSON host line must not crash the session — it is skipped
    and the next valid message is delivered."""
    import os

    from opensquilla.cli.tui.opentui.messages import HostInputSubmit

    read_fd, write_fd = os.pipe()
    os.write(write_fd, b"\xff\xfe invalid utf-8 bytes\n")  # would crash a strict reader
    os.write(write_fd, b"plain text, not json\n")  # unparseable -> skipped
    os.write(write_fd, b'{"type":"input.submit","text":"survived"}\n')  # valid
    os.close(write_fd)

    bridge = OpenTuiBridge()
    # Mirror bridge.start()'s read-pipe configuration (errors="replace").
    bridge._from_host_file = os.fdopen(read_fd, "r", encoding="utf-8", errors="replace")
    try:
        message = await bridge.next_message()
        assert isinstance(message, HostInputSubmit)
        assert message.text == "survived"
    finally:
        bridge._from_host_file.close()


@pytest.mark.asyncio
async def test_next_message_tolerates_malformed_line_logging_failure(monkeypatch) -> None:
    """Diagnostic logging failures must not turn skipped garbage into a crash."""

    from opensquilla.cli.tui.opentui.messages import HostInputSubmit

    def raise_closed_file(*_args: object, **_kwargs: object) -> None:
        raise ValueError("I/O operation on closed file")

    monkeypatch.setattr(bridge_module.log, "warning", raise_closed_file)

    bridge = OpenTuiBridge()
    bridge._from_host_file = io.StringIO(
        'plain text, not json\n{"type":"input.submit","text":"survived"}\n'
    )

    message = await bridge.next_message()

    assert isinstance(message, HostInputSubmit)
    assert message.text == "survived"


@pytest.mark.asyncio
async def test_close_does_not_treat_intentional_shutdown_as_crash() -> None:
    bridge = OpenTuiBridge()
    await _attach_exited_process(bridge, code=7, stderr="ignored\n")

    # close() flips the closing guard, reaps the child, and cancels stderr draining
    # without raising even though the child exited non-zero.
    await bridge.close()

    assert bridge._stderr_task is None
    assert bridge._process is None


@pytest.mark.asyncio
@pytest.mark.skipif(
    sys.platform.startswith("win"),
    reason="OpenTUI bridge currently uses POSIX fd inheritance via pass_fds",
)
async def test_start_surfaces_reason_and_cleans_up_when_host_crashes_on_launch(
    tmp_path, monkeypatch
) -> None:
    # A stand-in "host" that crashes immediately, exercising the real start()
    # handshake, fd plumbing, stderr capture, and crash detection without Bun.
    host_script = tmp_path / "fake_host.py"
    host_script.write_text(
        "import sys\nsys.stderr.write('startup boom\\n')\nsys.exit(1)\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        bridge_module,
        "check_opentui_host_available",
        lambda **_kwargs: RendererBackendAvailability(available=True),
    )

    bridge = OpenTuiBridge(runtime_bin=sys.executable, package_dir=tmp_path, ready_timeout=5.0)
    bridge.paths = OpenTuiHostPaths(package_dir=tmp_path, main_script=host_script)

    with pytest.raises(OpenTuiBridgeError) as exc_info:
        await bridge.start()

    message = str(exc_info.value)
    assert "code 1" in message
    assert "startup boom" in message
    # start() must not leak the child process or stderr drain task on failure.
    assert bridge._process is None
    assert bridge._stderr_task is None


@pytest.mark.asyncio
async def test_next_message_gives_up_after_a_malformed_line_flood() -> None:
    """A wedged sidecar flooding garbage must escalate to a raise instead of
    spinning the read loop forever."""
    bridge = OpenTuiBridge()
    bridge._from_host_file = io.StringIO("plain text, not json\n" * 65)

    with pytest.raises(HostToPythonMessageError):
        await bridge.next_message()


@pytest.mark.asyncio
async def test_next_message_delivers_after_exactly_the_flood_limit() -> None:
    """The escalation threshold is strict: 64 consecutive garbage lines are
    still skipped and the following valid message is delivered."""
    bridge = OpenTuiBridge()
    bridge._from_host_file = io.StringIO(
        "plain text, not json\n" * 64 + '{"type":"input.submit","text":"survived"}\n'
    )

    message = await bridge.next_message()

    assert message == HostInputSubmit(text="survived")


@pytest.mark.asyncio
@pytest.mark.skipif(
    sys.platform.startswith("win"),
    reason="OpenTUI bridge currently uses POSIX fd inheritance via pass_fds",
)
async def test_close_kills_wedged_host_instead_of_deadlocking(tmp_path, monkeypatch) -> None:
    """A host that never becomes ready, ignores SIGTERM, and never writes keeps
    a reader thread parked in readline holding the file lock. close() must kill
    the child (EOF-ing the pipe) BEFORE closing the read file, otherwise
    file.close() blocks the event loop forever waiting for that lock."""
    host_script = tmp_path / "wedged_host.py"
    host_script.write_text(
        "import signal, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        bridge_module,
        "check_opentui_host_available",
        lambda **_kwargs: RendererBackendAvailability(available=True),
    )

    bridge = OpenTuiBridge(runtime_bin=sys.executable, package_dir=tmp_path, ready_timeout=0.5)
    bridge.paths = OpenTuiHostPaths(package_dir=tmp_path, main_script=host_script)

    with pytest.raises(OpenTuiBridgeError, match="did not become ready"):
        await asyncio.wait_for(bridge.start(), timeout=20.0)

    assert bridge._process is None
    assert bridge._from_host_file is None


@pytest.mark.asyncio
async def test_send_nowait_escapes_lone_surrogates_instead_of_raising() -> None:
    """Serialized frames keep non-ASCII text verbatim, so a lone surrogate
    (e.g. a surrogateescape-decoded filename in a completion item) must be
    escaped by the pipe encoding, not raise an unwrapped UnicodeEncodeError."""
    read_fd, write_fd = os.pipe()
    bridge = OpenTuiBridge()
    # Mirror bridge.start()'s write-pipe configuration (errors="backslashreplace").
    bridge._to_host_file = os.fdopen(
        write_fd, "w", encoding="utf-8", errors="backslashreplace", buffering=1
    )

    bridge.send_nowait("scrollback.write", ScrollbackWrite(text="file_\udc80.txt"))

    bridge._to_host_file.close()
    bridge._to_host_file = None
    with os.fdopen(read_fd, "rb") as reader:
        data = reader.read()
    assert data.endswith(b"\n")
    assert b"\\udc80" in data


@pytest.mark.asyncio
async def test_send_nowait_wraps_closed_pipe_write_as_bridge_error() -> None:
    bridge = OpenTuiBridge()
    closed = io.StringIO()
    closed.close()
    bridge._to_host_file = closed

    with pytest.raises(OpenTuiBridgeError, match="IPC write failed"):
        bridge.send_nowait("shutdown")


@pytest.mark.asyncio
async def test_start_reports_missing_bun_reason_instead_of_spawn_error(monkeypatch) -> None:
    monkeypatch.setattr(bridge_module.os, "name", "posix")
    monkeypatch.setattr(bridge_module.shutil, "which", lambda _cmd: None)

    bridge = OpenTuiBridge()

    assert bridge.runtime_bin is None
    with pytest.raises(OpenTuiBridgeError, match="Bun is not installed"):
        await bridge.start()


@pytest.mark.asyncio
async def test_start_reports_bogus_runtime_bin_with_actionable_reason(
    tmp_path, monkeypatch
) -> None:
    package_dir = tmp_path / "package"
    (package_dir / "node_modules" / "@opentui" / "core").mkdir(parents=True)
    (package_dir / "src").mkdir()
    (package_dir / "src" / "main.mjs").write_text("", encoding="utf-8")
    monkeypatch.setattr(bridge_module.os, "name", "posix")

    bridge = OpenTuiBridge(
        runtime_bin=str(tmp_path / "no-such-runtime"), package_dir=package_dir
    )

    with pytest.raises(OpenTuiBridgeError, match="not executable"):
        await bridge.start()


@pytest.mark.asyncio
@pytest.mark.skipif(
    sys.platform.startswith("win"),
    reason="OpenTUI bridge currently uses POSIX fd inheritance via pass_fds",
)
async def test_start_wraps_vanished_runtime_as_bridge_error(tmp_path, monkeypatch) -> None:
    """A runtime that disappears between the availability check and the spawn
    must still surface as a catchable OpenTuiBridgeError, not FileNotFoundError."""
    monkeypatch.setattr(
        bridge_module,
        "check_opentui_host_available",
        lambda **_kwargs: RendererBackendAvailability(available=True),
    )

    bridge = OpenTuiBridge(runtime_bin=str(tmp_path / "vanished-bin"), package_dir=tmp_path)

    with pytest.raises(OpenTuiBridgeError, match="not executable"):
        await bridge.start()


@pytest.mark.asyncio
async def test_writer_task_keeps_loop_responsive_and_preserves_frame_order() -> None:
    gate = threading.Event()
    written: list[str] = []

    class _StalledPipe:
        def write(self, frame: str) -> None:
            gate.wait(timeout=10.0)
            written.append(frame)

        def flush(self) -> None:
            return None

        def close(self) -> None:
            return None

    bridge = OpenTuiBridge()
    bridge._to_host_file = _StalledPipe()
    bridge._write_queue = asyncio.Queue(maxsize=64)
    bridge._writer_task = asyncio.create_task(bridge._drain_writes())

    for index in range(3):
        bridge.send_nowait("scrollback.write", ScrollbackWrite(text=f"frame-{index}"))
    await asyncio.sleep(0.05)
    # The writer thread is parked on the stalled pipe, yet the loop kept
    # running and enqueueing stayed instant.
    assert written == []
    bridge.send_nowait("scrollback.write", ScrollbackWrite(text="frame-3"))

    gate.set()
    await bridge._flush_writes(timeout=5.0)

    texts = [json.loads(frame)["text"] for frame in written]
    assert texts == [f"frame-{index}" for index in range(4)]


@pytest.mark.asyncio
async def test_host_crash_triggers_terminal_restore(monkeypatch) -> None:
    bridge = OpenTuiBridge()
    restored: list[bool] = []
    monkeypatch.setattr(bridge, "_restore_terminal", lambda: restored.append(True))
    await _attach_exited_process(bridge, code=3, stderr="fatal: boom\n")

    with pytest.raises(OpenTuiBridgeError):
        await bridge.next_message()

    assert restored == [True]


@pytest.mark.asyncio
async def test_clean_host_exit_skips_terminal_restore(monkeypatch) -> None:
    bridge = OpenTuiBridge()
    restored: list[bool] = []
    monkeypatch.setattr(bridge, "_restore_terminal", lambda: restored.append(True))
    await _attach_exited_process(bridge, code=0, stderr="")

    assert await bridge.next_message() is None
    await bridge.close()

    assert restored == []


def test_restore_terminal_writes_reset_sequence_once() -> None:
    bridge = OpenTuiBridge()
    read_fd, write_fd = os.pipe()
    try:
        bridge._tty_fd = write_fd
        bridge._restore_terminal()
        bridge._restore_terminal()
    finally:
        os.close(write_fd)
    with os.fdopen(read_fd, "rb") as reader:
        data = reader.read()

    assert data == bridge_module._TERMINAL_RESET_SEQUENCE
    assert b"\x1b[?1049l" in data
    assert b"\x1b[?25h" in data
