"""Python side helpers for the OpenTUI footer host."""

from __future__ import annotations

import asyncio
import os
import shutil
import signal
import sys
from collections import deque
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

from opensquilla.cli.tui.backend.transcript import ViewportProjection
from opensquilla.cli.tui.opentui.messages import (
    HostError,
    HostReady,
    HostToPythonMessage,
    HostToPythonMessageError,
    ScrollbackWrite,
    host_message_from_json,
    python_message_to_json,
)
from opensquilla.cli.tui.renderers.selection import (
    RendererBackendAvailability,
)

try:
    import termios
except ImportError:  # pragma: no cover - Windows: the fd bridge is unsupported there
    termios = None  # type: ignore[assignment]

DEFAULT_HOST_PACKAGE_DIR = Path(__file__).resolve().parent / "package"
DEFAULT_READY_TIMEOUT_SECONDS = 5.0
# Tolerate a burst of unparseable host lines (skip them) before giving up, so a
# stray corrupted line never tears down the UI but a wedged sidecar still does.
_MAX_CONSECUTIVE_MALFORMED_LINES = 64
# Frames queued for the host before the bridge gives up. A healthy host drains
# far faster than Python produces, so hitting this bound means the host stopped
# reading; erroring beats growing the queue without limit.
_WRITE_QUEUE_MAX_FRAMES = 8192
# Best-effort tty sanity reset for an abnormally dead host: leave the alternate
# screen, disable mouse tracking (incl. SGR mode) and bracketed paste, show the
# cursor, and clear attributes. Every sequence is a no-op when already off.
_TERMINAL_RESET_SEQUENCE = (
    b"\x1b[?1049l\x1b[?1000l\x1b[?1002l\x1b[?1003l\x1b[?1006l\x1b[?2004l\x1b[?25h\x1b[0m"
)

log = structlog.get_logger(__name__)


class OpenTuiBridgeError(RuntimeError):
    """Raised when the OpenTUI host process cannot be used."""


@dataclass(frozen=True)
class OpenTuiHostPaths:
    package_dir: Path = DEFAULT_HOST_PACKAGE_DIR
    main_script: Path = DEFAULT_HOST_PACKAGE_DIR / "src" / "main.mjs"

    @property
    def opentui_core_dir(self) -> Path:
        return self.package_dir / "node_modules" / "@opentui" / "core"


def check_opentui_host_available(
    *,
    package_dir: Path = DEFAULT_HOST_PACKAGE_DIR,
    runtime_bin: str | None = None,
) -> RendererBackendAvailability:
    """Check whether the local Bun/OpenTUI host can be launched."""

    if os.name == "nt":
        return RendererBackendAvailability(
            available=False,
            reason="OpenTUI file-descriptor bridge is not supported on Windows yet",
        )

    if runtime_bin:
        # Validate a caller-supplied runtime the same way the default is probed,
        # so a bogus binary surfaces here as an actionable reason instead of a
        # raw FileNotFoundError out of the spawn.
        if not shutil.which(runtime_bin):
            return RendererBackendAvailability(
                available=False,
                reason=f"OpenTUI host runtime is not executable: {runtime_bin}",
            )
    elif not shutil.which("bun"):
        return RendererBackendAvailability(
            available=False,
            reason="Bun is not installed or is not on PATH",
        )

    paths = OpenTuiHostPaths(package_dir=package_dir)
    if not paths.opentui_core_dir.exists():
        return RendererBackendAvailability(
            available=False,
            reason=(
                "OpenTUI host dependency @opentui/core is not installed. "
                f"Run: bun install --cwd {package_dir}"
            ),
        )
    if not paths.main_script.exists():
        return RendererBackendAvailability(
            available=False,
            reason=f"OpenTUI host entrypoint is missing: {paths.main_script}",
        )
    return RendererBackendAvailability(available=True)


class OpenTuiBridge:
    """fd-based JSON-line IPC bridge to the Bun/OpenTUI footer host."""

    def __init__(
        self,
        *,
        runtime_bin: str | None = None,
        package_dir: Path = DEFAULT_HOST_PACKAGE_DIR,
        env: Mapping[str, str] | None = None,
        ready_timeout: float = DEFAULT_READY_TIMEOUT_SECONDS,
    ) -> None:
        # No literal fallback here: when Bun is missing this stays None so
        # start()'s availability check reports the friendly reason instead of
        # the spawn failing with a raw FileNotFoundError.
        self.runtime_bin = runtime_bin or shutil.which("bun")
        self.paths = OpenTuiHostPaths(package_dir=package_dir)
        self.env = dict(env or {})
        self.ready_timeout = ready_timeout
        self._process: asyncio.subprocess.Process | None = None
        self._to_host_file: Any | None = None
        self._from_host_file: Any | None = None
        self._stderr_lines: deque[str] = deque(maxlen=50)
        self._stderr_task: asyncio.Task[None] | None = None
        self._closing = False
        self._write_queue: asyncio.Queue[str | None] | None = None
        self._writer_task: asyncio.Task[None] | None = None
        self._write_error: OpenTuiBridgeError | None = None
        self._tty_fd: int | None = None
        self._saved_termios: list[Any] | None = None
        self._terminal_restored = False

    async def start(self) -> None:
        runtime_bin = self.runtime_bin or shutil.which("bun")
        availability = check_opentui_host_available(
            package_dir=self.paths.package_dir,
            runtime_bin=runtime_bin,
        )
        if runtime_bin is None or not availability.available:
            raise OpenTuiBridgeError(availability.reason or "OpenTUI host unavailable")

        to_host_read, to_host_write = os.pipe()
        from_host_read, from_host_write = os.pipe()
        for fd in (to_host_read, from_host_write):
            os.set_inheritable(fd, True)
        for fd in (to_host_write, from_host_read):
            os.set_inheritable(fd, False)

        env = os.environ.copy()
        env.update(self.env)
        env["OPENSQUILLA_OPENTUI_FROM_PYTHON_FD"] = str(to_host_read)
        env["OPENSQUILLA_OPENTUI_TO_PYTHON_FD"] = str(from_host_write)

        # The host owns the shared tty (raw mode, alternate screen, mouse
        # tracking). Snapshot the current termios now so an abnormal host death
        # can restore a usable shell.
        self._save_terminal_state()

        try:
            self._process = await asyncio.create_subprocess_exec(
                runtime_bin,
                str(self.paths.main_script),
                cwd=str(self.paths.package_dir),
                env=env,
                pass_fds=(to_host_read, from_host_write),
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            _close_fds(to_host_read, to_host_write, from_host_read, from_host_write)
            raise OpenTuiBridgeError(
                f"OpenTUI host runtime is not executable: {runtime_bin}"
            ) from exc
        except Exception:
            _close_fds(to_host_read, to_host_write, from_host_read, from_host_write)
            raise

        os.close(to_host_read)
        os.close(from_host_write)
        # errors="backslashreplace" so a lone surrogate (e.g. a surrogateescape-
        # decoded non-UTF-8 filename flowing into completion items) never raises
        # a hard UnicodeEncodeError mid-write; the host sees an escaped byte
        # instead of the session tearing down.
        self._to_host_file = os.fdopen(
            to_host_write, "w", encoding="utf-8", errors="backslashreplace", buffering=1
        )
        # errors="replace" so a corrupted byte from the host never raises a hard
        # UnicodeDecodeError mid-read; the line is still delivered (and skipped if
        # it no longer parses) instead of tearing down the UI.
        self._from_host_file = os.fdopen(from_host_read, "r", encoding="utf-8", errors="replace")
        # All frames go through a single queue-draining writer task: send stays
        # non-blocking on the event loop even when the host stops reading and
        # the pipe fills, and the one queue preserves global frame order.
        self._write_queue = asyncio.Queue(maxsize=_WRITE_QUEUE_MAX_FRAMES)
        self._writer_task = asyncio.create_task(self._drain_writes())
        # Capture the host's stderr so a crash leaves a diagnosable reason instead
        # of corrupting the terminal or vanishing. Draining it also keeps the
        # child from blocking on a full stderr pipe.
        self._stderr_task = asyncio.create_task(self._drain_stderr())

        # Record which main.mjs this Bun host actually loaded. A stale, still-running
        # host keeps serving the JS it spawned with, so a "fixed" frontend can look
        # broken until the old process is killed. Logging the script's mtime + the
        # child PID at spawn makes "old process running old code" diagnosable: compare
        # the logged mtime against the source file's current mtime.
        self._log_host_version()

        try:
            message = await asyncio.wait_for(self.next_message(), timeout=self.ready_timeout)
        except TimeoutError:
            detail = await self._stderr_tail()
            await self.close()
            reason = f"OpenTUI host did not become ready within {self.ready_timeout:.1f}s"
            raise OpenTuiBridgeError(f"{reason} ({detail})" if detail else reason) from None
        except BaseException:
            # next_message already surfaces a crash reason (incl. captured stderr);
            # make sure we never leak the child process or stderr drain task.
            await self.close()
            raise
        if isinstance(message, HostReady):
            return
        await self.close()
        if isinstance(message, HostError):
            raise OpenTuiBridgeError(message.message)
        raise OpenTuiBridgeError(f"OpenTUI host did not become ready: {message!r}")

    def _log_host_version(self) -> None:
        script = self.paths.main_script
        try:
            mtime = script.stat().st_mtime
            mtime_iso = datetime.fromtimestamp(mtime, tz=UTC).isoformat()
        except OSError:
            mtime_iso = "unknown"
        pid = self._process.pid if self._process is not None else None
        log.info(
            "opentui.host.spawned",
            main_script=str(script),
            main_script_mtime=mtime_iso,
            host_pid=pid,
        )

    async def send(self, message_type: str, payload: object | None = None) -> None:
        self.send_nowait(message_type, payload)

    def send_nowait(self, message_type: str, payload: object | None = None) -> None:
        if self._to_host_file is None:
            raise OpenTuiBridgeError("OpenTUI bridge is not started")
        if self._write_error is not None:
            raise OpenTuiBridgeError("OpenTUI host IPC write failed") from self._write_error
        frame = python_message_to_json(message_type, payload)
        queue = self._write_queue
        writer = self._writer_task
        if queue is None or writer is None or writer.done():
            # No writer task (bridge wired up without start(), or already
            # draining down): fall back to a direct synchronous write.
            self._write_frame_blocking(frame)
            return
        # Enqueueing synchronously (no await point) keeps frame order exactly
        # equal to call order, even for fire-and-forget sender tasks.
        try:
            queue.put_nowait(frame)
        except asyncio.QueueFull:
            raise OpenTuiBridgeError(
                "OpenTUI host stopped reading IPC frames (write queue overflow)"
            ) from None

    def _write_frame_blocking(self, frame: str) -> None:
        file = self._to_host_file
        if file is None:
            raise OpenTuiBridgeError("OpenTUI bridge is not started")
        try:
            file.write(frame)
            file.flush()
        except (OSError, ValueError) as exc:
            # ValueError covers writes on a closed file and any residual
            # UnicodeError the backslashreplace pipe encoding does not absorb.
            raise OpenTuiBridgeError("OpenTUI host IPC write failed") from exc

    async def _drain_writes(self) -> None:
        """Writer task: drain queued frames to the host off the event loop."""
        queue = self._write_queue
        if queue is None:
            return
        while True:
            frame = await queue.get()
            try:
                if frame is None:
                    return
                try:
                    await asyncio.to_thread(self._write_frame_blocking, frame)
                except OpenTuiBridgeError as exc:
                    # Remember the failure so the next send raises it; frames
                    # still queued are undeliverable and dropped with the pipe.
                    self._write_error = exc
                    return
            finally:
                queue.task_done()

    async def _flush_writes(self, timeout: float) -> None:
        """Ask the writer to drain everything queued so far, then stop."""
        queue = self._write_queue
        task = self._writer_task
        if queue is None or task is None or task.done():
            return
        with suppress(asyncio.QueueFull):
            queue.put_nowait(None)
        with suppress(asyncio.TimeoutError):
            await asyncio.wait_for(asyncio.shield(task), timeout=timeout)

    async def next_message(self) -> HostToPythonMessage | None:
        if self._from_host_file is None:
            raise OpenTuiBridgeError("OpenTUI bridge is not started")
        malformed = 0
        while True:
            line = await asyncio.to_thread(self._from_host_file.readline)
            if line == "":
                await self._raise_if_host_crashed()
                return None
            if not line.strip():
                continue
            try:
                return host_message_from_json(line)
            except HostToPythonMessageError as exc:
                # A single corrupted/garbage line must not kill the session — skip
                # it. Only give up if the host floods unparseable output, which
                # signals a genuinely wedged sidecar.
                malformed += 1
                if malformed > _MAX_CONSECUTIVE_MALFORMED_LINES:
                    raise
                with suppress(Exception):
                    log.warning("opentui.host.malformed_line", error=str(exc))
                continue

    async def _drain_stderr(self) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return
        try:
            while True:
                raw = await process.stderr.readline()
                if not raw:
                    break
                text = raw.decode("utf-8", errors="replace").rstrip("\n")
                if text:
                    self._stderr_lines.append(text)
        except asyncio.CancelledError:
            raise
        except Exception:  # pragma: no cover - defensive: never let drain crash
            return

    async def _stderr_tail(self) -> str:
        task = self._stderr_task
        if task is not None and not task.done():
            with suppress(asyncio.TimeoutError, asyncio.CancelledError):
                await asyncio.wait_for(asyncio.shield(task), timeout=0.5)
        return " | ".join(self._stderr_lines)

    async def _raise_if_host_crashed(self) -> None:
        """Distinguish a host crash from a clean EOF when the read pipe closes."""
        if self._closing:
            return
        process = self._process
        if process is None:
            return
        with suppress(asyncio.TimeoutError):
            await asyncio.wait_for(process.wait(), timeout=1.0)
        returncode = process.returncode
        if returncode is None or returncode == 0:
            return
        # The dead host never ran its own terminal teardown; reset the tty
        # before raising so the crash reason is readable in a sane shell.
        self._restore_terminal()
        detail = await self._stderr_tail()
        message = f"OpenTUI host exited with code {returncode}"
        if detail:
            message = f"{message}: {detail}"
        raise OpenTuiBridgeError(message)

    async def close(self) -> None:
        self._closing = True
        process = self._process
        if self._to_host_file is not None:
            with suppress(Exception):
                self.send_nowait("shutdown")
            # Deliver everything still queued (including the shutdown frame) so
            # a healthy host can exit on its own before any signal is sent.
            await self._flush_writes(timeout=1.0)
        if process is not None and process.returncode is None:
            with suppress(asyncio.TimeoutError):
                await asyncio.wait_for(process.wait(), timeout=0.5)
        # Terminate the child BEFORE closing the pipe files. A blocked reader
        # (or writer) thread holds the file's internal lock while parked in the
        # pipe syscall, so file.close() would deadlock the event loop until the
        # host produced data; killing the child first EOF/EPIPEs the pipes and
        # releases those threads.
        if process is not None and process.returncode is None:
            with suppress(ProcessLookupError):
                process.send_signal(signal.SIGTERM)
            with suppress(asyncio.TimeoutError):
                await asyncio.wait_for(process.wait(), timeout=1.0)
            if process.returncode is None:
                process.kill()
                await process.wait()
        writer_task = self._writer_task
        if writer_task is not None:
            if not writer_task.done():
                writer_task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await writer_task
            self._writer_task = None
        self._write_queue = None
        if self._to_host_file is not None:
            with suppress(Exception):
                self._to_host_file.close()
            self._to_host_file = None
        if self._from_host_file is not None:
            with suppress(Exception):
                self._from_host_file.close()
            self._from_host_file = None
        stderr_task = self._stderr_task
        if stderr_task is not None:
            stderr_task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await stderr_task
            self._stderr_task = None
        if process is not None and process.returncode not in (None, 0):
            # Nonzero/signal exit: the host may have died without restoring the
            # terminal it owned. A clean exit (0) already restored it.
            self._restore_terminal()
        self._process = None

    def _save_terminal_state(self) -> None:
        self._terminal_restored = False
        self._tty_fd = None
        self._saved_termios = None
        fd = _controlling_tty_fd()
        if fd is None:
            return
        self._tty_fd = fd
        if termios is None:
            return
        with suppress(Exception):
            self._saved_termios = termios.tcgetattr(fd)

    def _restore_terminal(self) -> None:
        """Best-effort tty reset after the host died without its own teardown."""
        if self._terminal_restored:
            return
        self._terminal_restored = True
        fd = self._tty_fd
        if fd is None:
            return
        if termios is not None and self._saved_termios is not None:
            with suppress(Exception):
                termios.tcsetattr(fd, termios.TCSADRAIN, self._saved_termios)
        with suppress(Exception):
            os.write(fd, _TERMINAL_RESET_SEQUENCE)

    async def write_scrollback(self, payload: str) -> None:
        await self.send("scrollback.write", ScrollbackWrite(text=payload))


def _close_fds(*fds: int) -> None:
    for fd in fds:
        with suppress(OSError):
            os.close(fd)


def _controlling_tty_fd() -> int | None:
    """Locate a tty fd shared with the host, or None when not on a terminal."""
    for stream in (sys.stdout, sys.stderr, sys.stdin):
        try:
            fd = stream.fileno()
        except (AttributeError, OSError, ValueError):
            continue
        if os.isatty(fd):
            return fd
    return None


@dataclass
class OpenTuiReplayRenderer:
    """Headless renderer facade used for backend contract tests and evaluation."""

    buffer: str = ""
    reasoning_buffer: str = ""
    intermediate_buffer: str = ""
    flush_count: int = 0
    statuses: list[tuple[str, str]] = field(default_factory=list)
    tool_events: list[tuple[str, str | None]] = field(default_factory=list)

    async def aappend_text(self, delta: str, *, presentation: str = "answer") -> None:
        if presentation == "intermediate":
            self.intermediate_buffer += delta
        else:
            self.buffer += delta
        self.flush_count += 1

    async def aappend_reasoning(self, delta: str) -> None:
        self.reasoning_buffer += delta

    async def atool_start(
        self,
        name: str,
        args: dict[str, Any] | None = None,
        tool_use_id: str | None = None,
    ) -> None:
        del args
        self.tool_events.append((f"start:{name}", tool_use_id))

    async def atool_finished(
        self,
        tool_use_id: str | None,
        *,
        success: bool,
        elapsed: float | None = None,
        error: str | None = None,
        result: object | None = None,
    ) -> None:
        del elapsed, error, result
        self.tool_events.append(("done" if success else "error", tool_use_id))

    async def astatus(self, message: str, *, style: str = "dim") -> None:
        self.statuses.append((message, style))

    async def aerror(self, message: str) -> None:
        self.statuses.append((message, "error"))

    def pulse(self) -> None:
        return None

    async def afinalize(self, usage: Any | None = None, *, cancelled: bool = False) -> None:
        del usage
        if cancelled:
            self.statuses.append(("cancelled", "dim"))

    async def aclose(self) -> None:
        return None

    def render_structured_layout(
        self,
        *,
        plugin_snapshots: dict[str, object],
        transcript_projection: ViewportProjection,
    ) -> dict[str, int | tuple[str, ...]]:
        return {
            "plugin_slots": tuple(sorted(plugin_snapshots)),
            "visible_items": len(transcript_projection.items),
            "total_items": transcript_projection.total_items,
            "total_rows": transcript_projection.total_rows,
        }


@dataclass(frozen=True)
class OpenTuiRendererBackend:
    backend_id: str = "opentui"
    supports_structured_ui: bool = True
    supports_streaming_fast_path: bool = True

    def is_available(self) -> RendererBackendAvailability:
        return check_opentui_host_available()

    def create_renderer(self, **kwargs: Any) -> OpenTuiReplayRenderer:
        del kwargs
        return OpenTuiReplayRenderer()
