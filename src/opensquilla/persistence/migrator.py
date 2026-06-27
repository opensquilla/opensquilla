"""Schema migrator — thin wrapper over yoyo-migrations.

Each migration module owns its versioned up/down policy; gateway boot applies
pending migrations before code paths depend on the new schema.
"""

from __future__ import annotations

import builtins
import contextlib
import logging
import os
import sqlite3
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

from yoyo import exceptions, get_backend, read_migrations

log = logging.getLogger(__name__)


def _adapt_sqlite_datetime(value: datetime) -> str:
    return value.isoformat(" ")


def _ensure_sqlite_datetime_adapter() -> None:
    """Register the Python 3.12 replacement for sqlite3's deprecated default."""

    sqlite3.register_adapter(datetime, _adapt_sqlite_datetime)


def _to_yoyo_url(db_url: str) -> str:
    """Normalise a local SQLite path or URL into a yoyo-compatible URL.

    Accepts: ``path/to.db``, ``:memory:``, or a pre-formed ``sqlite:///…`` URL.
    Returns a URL yoyo ``get_backend`` understands.
    """
    if "://" in db_url:
        return db_url
    if db_url == ":memory:":
        return "sqlite:///:memory:"
    # bare filesystem path — normalise to absolute so yoyo opens the same db
    # regardless of the worker cwd.
    return "sqlite:///" + os.path.abspath(db_url)


def _sqlite_path_from_db_url(db_url: str) -> Path | None:
    """Return a local SQLite database path when direct lock inspection is safe."""

    if db_url == ":memory:":
        return None
    if "://" not in db_url:
        return Path(db_url).expanduser().resolve()

    parsed = urlparse(db_url)
    if parsed.scheme != "sqlite" or parsed.netloc:
        return None
    if parsed.path in {"", "/:memory:"}:
        return None

    path = unquote(parsed.path)
    if os.name != "nt" and path.startswith("//") and not path.startswith("///"):
        path = path[1:]
    return Path(path).expanduser().resolve()


def _is_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        last_error = int(kernel32.GetLastError())
        return last_error == 5

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _read_yoyo_lock_pids(db_path: Path) -> list[int] | None:
    try:
        connection = sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        log.warning(
            "migrator.lock_inspect_failed",
            extra={"db_path": str(db_path), "error": str(exc)},
        )
        return None

    try:
        rows = connection.execute("SELECT pid FROM yoyo_lock").fetchall()
    except sqlite3.Error as exc:
        log.warning(
            "migrator.lock_inspect_failed",
            extra={"db_path": str(db_path), "error": str(exc)},
        )
        return None
    finally:
        connection.close()

    pids: list[int] = []
    for (raw_pid,) in rows:
        try:
            pids.append(int(raw_pid))
        except (TypeError, ValueError):
            pids.append(0)
    return pids


def _clear_yoyo_lock(db_path: Path) -> bool:
    try:
        with sqlite3.connect(db_path) as connection:
            connection.execute("DELETE FROM yoyo_lock")
    except sqlite3.Error as exc:
        log.warning(
            "migrator.stale_lock_clear_failed",
            extra={"db_path": str(db_path), "error": str(exc)},
        )
        return False
    return True


def _recover_stale_yoyo_lock(db_url: str, error: exceptions.LockTimeout) -> bool:
    log.warning("migrator.lock_timeout", extra={"db_url": db_url, "error": str(error)})
    db_path = _sqlite_path_from_db_url(db_url)
    if db_path is None:
        return False

    pids = _read_yoyo_lock_pids(db_path)
    if not pids:
        return False

    live_pids = [pid for pid in pids if _is_pid_alive(pid)]
    if live_pids:
        log.warning(
            "migrator.lock_held_by_live_process",
            extra={"db_path": str(db_path), "pids": live_pids},
        )
        pid_text = ", ".join(str(pid) for pid in live_pids)
        raise exceptions.LockTimeout(
            f"Gateway migration database is locked by live process pid={pid_text} "
            f"at {db_path}"
        ) from error

    if not _clear_yoyo_lock(db_path):
        return False
    log.warning(
        "migrator.stale_lock_cleared",
        extra={"db_path": str(db_path), "pids": pids},
    )
    return True


@contextlib.contextmanager
def _yoyo_utf8_open() -> Iterator[None]:
    """Force yoyo's Migration.load() to read .py migrations as UTF-8.

    Why: yoyo's ``Migration.load`` calls ``open(self.path, "r")`` without an
    explicit encoding, so on Windows locales whose default codec is not UTF-8
    (e.g. zh-CN → GBK), any migration file containing non-ASCII docstrings
    (em-dashes, Chinese, etc.) raises UnicodeDecodeError at gateway boot. Patch
    the builtin scoped to the yoyo call window only.
    """
    real_open = builtins.open

    def utf8_open(file, mode="r", *args, **kwargs):  # type: ignore[no-untyped-def]
        if "b" not in mode and "encoding" not in kwargs:
            kwargs["encoding"] = "utf-8"
        return real_open(file, mode, *args, **kwargs)

    builtins.open = utf8_open  # type: ignore[assignment]
    try:
        yield
    finally:
        builtins.open = real_open  # type: ignore[assignment]


def apply_pending(db_url: str, migrations_dir: Path) -> list[str]:
    """Apply every migration in *migrations_dir* not yet recorded in *db_url*.

    Returns the ordered list of migration ids that were applied in this call.
    If no migrations are pending, returns ``[]``. Callers running at boot
    should log the return value for audit.
    """
    path = Path(migrations_dir)
    if not path.is_dir():
        log.warning("migrator.missing_dir", extra={"migrations_dir": str(path)})
        return []

    _ensure_sqlite_datetime_adapter()
    try:
        ids = _apply_pending_once(db_url, path)
    except exceptions.LockTimeout as exc:
        if not _recover_stale_yoyo_lock(db_url, exc):
            raise
        try:
            ids = _apply_pending_once(db_url, path)
        except exceptions.LockTimeout:
            log.warning("migrator.stale_lock_retry_failed", extra={"db_url": db_url})
            raise

    if ids:
        log.info("migrator.applied", extra={"count": len(ids), "ids": ids})
    return ids


def _apply_pending_once(db_url: str, migrations_dir: Path) -> list[str]:
    backend = get_backend(_to_yoyo_url(db_url))
    try:
        with _yoyo_utf8_open():
            migrations = read_migrations(str(migrations_dir))
            pending = backend.to_apply(migrations)
            ids = [m.id for m in pending]
            if not ids:
                return []

            with backend.lock():
                backend.apply_migrations(pending)
        return ids
    finally:
        close = getattr(backend, "close", None)
        if close is not None:
            close()
