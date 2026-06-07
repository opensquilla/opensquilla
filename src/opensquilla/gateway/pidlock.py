"""PID file + exclusive lock for the gateway process.

Prevents two gateway instances from sharing the same STATE_DIR.

Design:
- The pid file (``gateway.pid``) is always readable: written atomically then fsynced.
- The lock file (``gateway.pid.lock``) carries the OS exclusive byte-range lock so the
  pid file itself stays open for readers even while the lock is held.

Platform locking:
- Windows: msvcrt.locking(lock_fd, LK_NBLCK, 1) on gateway.pid.lock
- POSIX:   fcntl.flock(lock_fd, LOCK_EX | LOCK_NB) on gateway.pid.lock

Usage::

    lock = GatewayPidLock(state_dir)
    lock.acquire()          # raises SystemExit(1) if another live instance holds it
    # lock released automatically via atexit + signal handlers registered in acquire()
"""

from __future__ import annotations

import atexit
import datetime
import json
import logging
import os
import signal
import sys
from pathlib import Path
from typing import IO, Any, cast

log = logging.getLogger(__name__)

_PID_FILENAME = "gateway.pid"
_LOCK_FILENAME = "gateway.pid.lock"


class GatewayPidLock:
    """Exclusive PID-file lock for one gateway instance per STATE_DIR."""

    def __init__(self, state_dir: str | Path) -> None:
        self._state_dir = Path(state_dir)
        self._pid_path = self._state_dir / _PID_FILENAME
        self._lock_path = self._state_dir / _LOCK_FILENAME
        self._lock_fh: IO[bytes] | None = None
        # Cached payload written by this instance (readable without reopening the file).
        self._written: dict | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def acquire(self) -> None:
        """Acquire the PID file lock.

        Algorithm:
        1. If gateway.pid already exists, read it.
           - pid alive  → SystemExit(1) with STATE_DIR + pid in message.
           - pid dead   → log warning (stale), remove pid file, continue.
        1b. If gateway.pid is missing but gateway.pid.lock exists, the
            previous owner died without running the atexit / signal
            cleanup (kill -9, OOM, power loss). Treat the lock as
            stale: log it and unlink so the new instance can take
            over instead of `gateway start` waiting the full readiness
            timeout and reporting "another gateway is already
            running".
        2. Acquire exclusive OS lock on gateway.pid.lock (separate file so
           gateway.pid stays freely readable while the lock is held).
           - Lock fails (race) → SystemExit(1).
        3. Write pid + start_ts (ISO 8601) to gateway.pid, fsync.
        4. Register atexit + SIGTERM/SIGINT cleanup.
        """
        self._state_dir.mkdir(parents=True, exist_ok=True)

        # ── Step 1: check existing pid file ──────────────────────────
        if self._pid_path.exists():
            existing_pid = _read_pid_from_path(self._pid_path)
            if existing_pid is not None and _is_alive(existing_pid):
                log.error(
                    "gateway.pidlock.already_running",
                    extra={"pid": existing_pid, "state_dir": str(self._state_dir)},
                )
                print(
                    f"ERROR: Another gateway is already running "
                    f"(pid={existing_pid}, state_dir={self._state_dir}). "
                    f"Stop it first or remove {self._pid_path}.",
                    file=sys.stderr,
                )
                sys.exit(1)
            elif existing_pid is not None:
                log.warning(
                    "gateway.pidlock.stale_overwritten",
                    extra={"stale_pid": existing_pid, "state_dir": str(self._state_dir)},
                )
            try:
                self._pid_path.unlink(missing_ok=True)
            except OSError:
                pass
        elif self._lock_path.exists():
            # ── Step 1b: orphan lock file (no pid file) ───────────
            # The previous daemon died without running the cleanup
            # hooks (kill -9, OOM kill, power loss). The pid file is
            # gone, but the lock file is left behind and a fresh
            # `gateway start` would otherwise hit the "lock fails
            # (race)" branch below and time out. Recover the lock
            # and surface it in the log so the operator can see why
            # the new instance took over.
            log.warning(
                "gateway.pidlock.orphan_lock_recovered",
                extra={
                    "state_dir": str(self._state_dir),
                    "lock_path": str(self._lock_path),
                    "lock_age_seconds": _file_age_seconds(self._lock_path),
                },
            )
            try:
                self._lock_path.unlink(missing_ok=True)
            except OSError:
                pass

        # ── Step 2: exclusive OS lock on the lock file ────────────────
        lock_fh = open(str(self._lock_path), "w+b")  # noqa: WPS515

        if not _try_lock(lock_fh):
            # Race: another process won the lock between step 1 and now.
            existing_pid = _read_pid_from_path(self._pid_path)
            lock_fh.close()
            pid_str = str(existing_pid) if existing_pid is not None else "unknown"
            print(
                f"ERROR: Another gateway is already running "
                f"(pid={pid_str}, state_dir={self._state_dir}). "
                f"Stop it first or remove {self._pid_path}.",
                file=sys.stderr,
            )
            sys.exit(1)

        # ── Step 3: write pid + start_ts to the pid file ─────────────
        self._lock_fh = lock_fh
        self._write_pid()

        # ── Step 4: register cleanup ──────────────────────────────────
        self._register_cleanup()

    def release(self) -> None:
        """Release the lock and remove the PID file. Safe to call multiple times."""
        if self._lock_fh is None:
            return
        fh = self._lock_fh
        self._lock_fh = None
        try:
            _unlock(fh)
        except OSError:
            pass
        try:
            fh.close()
        except OSError:
            pass
        try:
            self._pid_path.unlink(missing_ok=True)
        except OSError:
            pass
        try:
            self._lock_path.unlink(missing_ok=True)
        except OSError:
            pass

    @property
    def pid(self) -> int | None:
        """The PID written to the pid file by this instance, or None before acquire()."""
        return self._written.get("pid") if self._written else None

    @property
    def start_ts(self) -> str | None:
        """The start_ts written to the pid file by this instance, or None before acquire()."""
        return self._written.get("start_ts") if self._written else None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _write_pid(self) -> None:
        self._written = {
            "pid": os.getpid(),
            "start_ts": datetime.datetime.now(datetime.UTC).isoformat(),
        }
        payload = json.dumps(self._written).encode()
        # Write to the pid file (not the lock file) so readers can open it freely.
        with open(str(self._pid_path), "wb") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())

    def _register_cleanup(self) -> None:
        atexit.register(self.release)

        def _handler(signum: int, frame: object) -> None:
            self.release()
            signal.signal(signum, signal.SIG_DFL)
            os.kill(os.getpid(), signum)

        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                signal.signal(sig, _handler)
            except (OSError, ValueError):
                pass


# ---------------------------------------------------------------------------
# Module-level helpers (no self state needed)
# ---------------------------------------------------------------------------


def _try_lock(fh: IO[bytes]) -> bool:
    if os.name == "nt":
        import msvcrt

        msvcrt_mod = cast(Any, msvcrt)
        try:
            fh.seek(0)
            msvcrt_mod.locking(fh.fileno(), msvcrt_mod.LK_NBLCK, 1)
            return True
        except OSError:
            return False
    else:
        import fcntl

        fcntl_mod = cast(Any, fcntl)
        try:
            fcntl_mod.flock(fh.fileno(), fcntl_mod.LOCK_EX | fcntl_mod.LOCK_NB)
            return True
        except OSError:
            return False


def _unlock(fh: IO[bytes]) -> None:
    if os.name == "nt":
        import msvcrt

        msvcrt_mod = cast(Any, msvcrt)
        try:
            fh.seek(0)
            msvcrt_mod.locking(fh.fileno(), msvcrt_mod.LK_UNLCK, 1)
        except OSError:
            pass
    else:
        import fcntl

        fcntl_mod = cast(Any, fcntl)
        try:
            fcntl_mod.flock(fh.fileno(), fcntl_mod.LOCK_UN)
        except OSError:
            pass


def _read_pid_from_path(path: Path) -> int | None:
    try:
        info = json.loads(path.read_bytes())
        return int(info["pid"])
    except Exception:  # noqa: BLE001
        return None


def _file_age_seconds(path: Path) -> float:
    """Return the wall-clock age of *path* in seconds, or 0.0 if it
    is missing / unreadable. Used for the orphan-lock-recovery log
    so the operator can see how long the dead lock was lying
    around.
    """
    try:
        return max(0.0, datetime.datetime.now().timestamp() - path.stat().st_mtime)
    except OSError:
        return 0.0


def _is_alive(pid: int) -> bool:
    if os.name == "nt":
        try:
            import ctypes

            ctypes_mod = cast(Any, ctypes)
            synchronize = 0x00100000
            handle = ctypes_mod.windll.kernel32.OpenProcess(synchronize, False, pid)
            if handle == 0:
                return False
            ctypes_mod.windll.kernel32.CloseHandle(handle)
            return True
        except Exception:  # noqa: BLE001
            return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True  # exists but not owned by us
