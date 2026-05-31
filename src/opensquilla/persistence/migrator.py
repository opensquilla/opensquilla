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

from yoyo import get_backend, read_migrations

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
    backend = get_backend(_to_yoyo_url(db_url))
    try:
        with _yoyo_utf8_open():
            migrations = read_migrations(str(path))
            pending = backend.to_apply(migrations)
            ids = [m.id for m in pending]
            if not ids:
                return []

            with backend.lock():
                backend.apply_migrations(pending)
        log.info("migrator.applied", extra={"count": len(ids), "ids": ids})
        return ids
    finally:
        close = getattr(backend, "close", None)
        if close is not None:
            close()
