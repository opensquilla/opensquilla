from __future__ import annotations

import asyncio
import io
import sys

import pytest

from opensquilla.cli.tui import opentui as _opentui_pkg  # noqa: F401  (ensure package import)
from opensquilla.cli.tui.opentui import bridge as bridge_module
from opensquilla.cli.tui.opentui.bridge import (
    OpenTuiBridge,
    OpenTuiBridgeError,
    OpenTuiHostPaths,
    check_opentui_host_available,
)
from opensquilla.cli.tui.renderers.selection import RendererBackendAvailability


def test_missing_opentui_host_dependencies_report_install_command(tmp_path) -> None:
    package_dir = tmp_path / "package"
    package_dir.mkdir()

    availability = check_opentui_host_available(package_dir=package_dir, runtime_bin="bun")

    assert availability.available is False
    assert availability.reason is not None
    assert "@opentui/core" in availability.reason
    assert f"bun install --cwd {package_dir}" in availability.reason


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
