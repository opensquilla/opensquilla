"""Python side helpers for the OpenTUI footer host."""

from __future__ import annotations

import asyncio
import os
import shutil
import signal
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

DEFAULT_HOST_PACKAGE_DIR = Path(__file__).resolve().parent / "package"
DEFAULT_READY_TIMEOUT_SECONDS = 5.0
# Tolerate a burst of unparseable host lines (skip them) before giving up, so a
# stray corrupted line never tears down the UI but a wedged sidecar still does.
_MAX_CONSECUTIVE_MALFORMED_LINES = 64

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

    resolved_runtime = runtime_bin or shutil.which("bun")
    if not resolved_runtime:
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
        self.runtime_bin = runtime_bin or shutil.which("bun") or "bun"
        self.paths = OpenTuiHostPaths(package_dir=package_dir)
        self.env = dict(env or {})
        self.ready_timeout = ready_timeout
        self._process: asyncio.subprocess.Process | None = None
        self._to_host_file: Any | None = None
        self._from_host_file: Any | None = None
        self._stderr_lines: deque[str] = deque(maxlen=50)
        self._stderr_task: asyncio.Task[None] | None = None
        self._closing = False

    async def start(self) -> None:
        availability = check_opentui_host_available(
            package_dir=self.paths.package_dir,
            runtime_bin=self.runtime_bin,
        )
        if not availability.available:
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

        try:
            self._process = await asyncio.create_subprocess_exec(
                self.runtime_bin,
                str(self.paths.main_script),
                cwd=str(self.paths.package_dir),
                env=env,
                pass_fds=(to_host_read, from_host_write),
                stderr=asyncio.subprocess.PIPE,
            )
        except Exception:
            _close_fds(to_host_read, to_host_write, from_host_read, from_host_write)
            raise

        os.close(to_host_read)
        os.close(from_host_write)
        self._to_host_file = os.fdopen(to_host_write, "w", encoding="utf-8", buffering=1)
        # errors="replace" so a corrupted byte from the host never raises a hard
        # UnicodeDecodeError mid-read; the line is still delivered (and skipped if
        # it no longer parses) instead of tearing down the UI.
        self._from_host_file = os.fdopen(
            from_host_read, "r", encoding="utf-8", errors="replace"
        )
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
        try:
            self._to_host_file.write(python_message_to_json(message_type, payload))
            self._to_host_file.flush()
        except OSError as exc:
            raise OpenTuiBridgeError("OpenTUI host IPC write failed") from exc

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
            with suppress(Exception):
                self._to_host_file.close()
            self._to_host_file = None
        if self._from_host_file is not None:
            with suppress(Exception):
                self._from_host_file.close()
            self._from_host_file = None
        if process is not None and process.returncode is None:
            with suppress(ProcessLookupError):
                process.send_signal(signal.SIGTERM)
            with suppress(asyncio.TimeoutError):
                await asyncio.wait_for(process.wait(), timeout=1.0)
            if process.returncode is None:
                process.kill()
                await process.wait()
        stderr_task = self._stderr_task
        if stderr_task is not None:
            stderr_task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await stderr_task
            self._stderr_task = None
        self._process = None

    async def write_scrollback(self, payload: str) -> None:
        await self.send("scrollback.write", ScrollbackWrite(text=payload))


def _close_fds(*fds: int) -> None:
    for fd in fds:
        with suppress(OSError):
            os.close(fd)


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
