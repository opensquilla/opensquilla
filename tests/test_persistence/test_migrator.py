from __future__ import annotations

import builtins
import contextlib
import sqlite3
import warnings
from pathlib import Path
from types import SimpleNamespace

import pytest
from yoyo import exceptions

from opensquilla.persistence import migrator
from opensquilla.persistence.migrator import apply_pending


def test_apply_pending_registers_python312_datetime_adapter(tmp_path: Path) -> None:
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    (migrations_dir / "V001__demo.py").write_text(
        "from yoyo import step\n"
        "__depends__ = set()\n"
        "steps = [step('CREATE TABLE demo (id INTEGER PRIMARY KEY)')]\n",
        encoding="utf-8",
    )

    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        applied = apply_pending(str(tmp_path / "demo.sqlite"), migrations_dir)

    assert applied == ["V001__demo"]


def test_apply_pending_forces_utf8_when_yoyo_loads_python_migrations(
    tmp_path: Path, monkeypatch
) -> None:
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    migration_file = migrations_dir / "V999__utf8.py"
    migration_file.write_text("marker = '— 界'\n", encoding="utf-8")

    real_open = builtins.open
    seen: dict[str, object] = {}

    def legacy_locale_open(file, mode="r", *args, **kwargs):  # type: ignore[no-untyped-def]
        if "b" not in mode and "encoding" not in kwargs:
            raise UnicodeDecodeError("gbk", b"\x80", 0, 1, "fake legacy locale")
        seen["encoding"] = kwargs.get("encoding")
        return real_open(file, mode, *args, **kwargs)

    def fake_read_migrations(path: str):
        assert path == str(migrations_dir)
        with open(migration_file) as handle:
            seen["content"] = handle.read()
        return [SimpleNamespace(id="V999__utf8")]

    class FakeBackend:
        def to_apply(self, migrations):
            seen["migrations"] = migrations
            return [SimpleNamespace(id="V999__utf8")]

        def lock(self):
            return contextlib.nullcontext()

        def apply_migrations(self, pending):
            seen["pending"] = [item.id for item in pending]

        def close(self):
            seen["closed"] = True

    monkeypatch.setattr(migrator.builtins, "open", legacy_locale_open)
    monkeypatch.setattr(migrator, "read_migrations", fake_read_migrations)
    monkeypatch.setattr(migrator, "get_backend", lambda _url: FakeBackend())

    applied = apply_pending(str(tmp_path / "demo.sqlite"), migrations_dir)

    assert applied == ["V999__utf8"]
    assert seen["encoding"] == "utf-8"
    assert seen["content"] == "marker = '— 界'\n"
    assert seen["pending"] == ["V999__utf8"]
    assert seen["closed"] is True


def _create_yoyo_lock(db_path: Path, pid: int) -> None:
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "CREATE TABLE yoyo_lock (locked INTEGER PRIMARY KEY, ctime TIMESTAMP, pid INTEGER)"
        )
        connection.execute(
            "INSERT INTO yoyo_lock (locked, ctime, pid) VALUES (1, CURRENT_TIMESTAMP, ?)",
            (pid,),
        )


def _yoyo_lock_pids(db_path: Path) -> list[int]:
    with sqlite3.connect(db_path) as connection:
        return [row[0] for row in connection.execute("SELECT pid FROM yoyo_lock")]


class _RaisingLock:
    def __init__(self, message: str = "Process 424242 has locked this database") -> None:
        self._message = message

    def __enter__(self) -> None:
        raise exceptions.LockTimeout(self._message)

    def __exit__(self, *_args) -> None:  # type: ignore[no-untyped-def]
        return None


class _FakeBackend:
    def __init__(self, lock_context: object, applied: list[list[str]], closed: list[str]) -> None:
        self._lock_context = lock_context
        self._applied = applied
        self._closed = closed

    def to_apply(self, migrations):  # type: ignore[no-untyped-def]
        return migrations

    def lock(self):
        return self._lock_context

    def apply_migrations(self, pending) -> None:  # type: ignore[no-untyped-def]
        self._applied.append([item.id for item in pending])

    def close(self) -> None:
        self._closed.append("closed")


def test_apply_pending_clears_dead_yoyo_lock_and_retries_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "sessions.db"
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    _create_yoyo_lock(db_path, 424242)

    applied: list[list[str]] = []
    closed: list[str] = []
    backends = [
        _FakeBackend(_RaisingLock(), applied, closed),
        _FakeBackend(contextlib.nullcontext(), applied, closed),
    ]

    monkeypatch.setattr(migrator, "_is_pid_alive", lambda _pid: False)
    monkeypatch.setattr(migrator, "read_migrations", lambda _path: [SimpleNamespace(id="V001")])
    monkeypatch.setattr(migrator, "get_backend", lambda _url: backends.pop(0))

    result = apply_pending(str(db_path), migrations_dir)

    assert result == ["V001"]
    assert applied == [["V001"]]
    assert closed == ["closed", "closed"]
    assert _yoyo_lock_pids(db_path) == []
    assert backends == []


def test_apply_pending_recovers_stale_yoyo_lock_with_real_backend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    (migrations_dir / "V001__real_backend.py").write_text(
        "from yoyo import step\n"
        "__depends__ = set()\n"
        "steps = [step('CREATE TABLE real_backend_demo (id INTEGER PRIMARY KEY)')]\n",
        encoding="utf-8",
    )
    db_path = tmp_path / "sessions.db"
    _create_yoyo_lock(db_path, 424242)
    real_get_backend = migrator.get_backend

    def get_fast_lock_backend(url: str):
        backend = real_get_backend(url)
        real_lock = backend.lock

        def fast_lock(timeout: float = 10):
            return real_lock(timeout=0.01)

        backend.lock = fast_lock  # type: ignore[method-assign]
        return backend

    monkeypatch.setattr(migrator, "_is_pid_alive", lambda _pid: False)
    monkeypatch.setattr(migrator, "get_backend", get_fast_lock_backend)

    result = apply_pending(str(db_path), migrations_dir)

    assert result == ["V001__real_backend"]
    assert _yoyo_lock_pids(db_path) == []
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='real_backend_demo'"
        ).fetchall()
    assert rows == [("real_backend_demo",)]


def test_apply_pending_does_not_clear_live_yoyo_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "sessions.db"
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    _create_yoyo_lock(db_path, 12345)

    applied: list[list[str]] = []
    closed: list[str] = []
    backends = [
        _FakeBackend(_RaisingLock("Process 12345 has locked this database"), applied, closed)
    ]

    monkeypatch.setattr(migrator, "_is_pid_alive", lambda pid: pid == 12345)
    monkeypatch.setattr(migrator, "read_migrations", lambda _path: [SimpleNamespace(id="V001")])
    monkeypatch.setattr(migrator, "get_backend", lambda _url: backends.pop(0))

    with pytest.raises(exceptions.LockTimeout, match="live process pid=12345"):
        apply_pending(str(db_path), migrations_dir)

    assert applied == []
    assert closed == ["closed"]
    assert _yoyo_lock_pids(db_path) == [12345]
    assert backends == []


def test_apply_pending_does_not_loop_when_stale_lock_retry_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "sessions.db"
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    _create_yoyo_lock(db_path, 424242)

    applied: list[list[str]] = []
    closed: list[str] = []
    backends = [
        _FakeBackend(_RaisingLock(), applied, closed),
        _FakeBackend(_RaisingLock("Database locked after cleanup"), applied, closed),
    ]

    monkeypatch.setattr(migrator, "_is_pid_alive", lambda _pid: False)
    monkeypatch.setattr(migrator, "read_migrations", lambda _path: [SimpleNamespace(id="V001")])
    monkeypatch.setattr(migrator, "get_backend", lambda _url: backends.pop(0))

    with pytest.raises(exceptions.LockTimeout, match="Database locked after cleanup"):
        apply_pending(str(db_path), migrations_dir)

    assert applied == []
    assert closed == ["closed", "closed"]
    assert _yoyo_lock_pids(db_path) == []
    assert backends == []


def test_sqlite_path_from_db_url_rejects_unsupported_database_urls() -> None:
    assert migrator._sqlite_path_from_db_url(":memory:") is None
    assert migrator._sqlite_path_from_db_url("sqlite:///:memory:") is None
    assert migrator._sqlite_path_from_db_url("postgresql://example/db") is None


def _write_demo_migration(migrations_dir: Path, name: str = "V001__demo") -> None:
    migrations_dir.mkdir(exist_ok=True)
    (migrations_dir / f"{name}.py").write_text(
        "from yoyo import step\n"
        "__depends__ = set()\n"
        f"steps = [step('CREATE TABLE {name.lower()} (id INTEGER PRIMARY KEY)')]\n",
        encoding="utf-8",
    )


def _record_applied_migration(db_path: Path, migration_id: str) -> None:
    """Simulate a newer build having applied an extra migration."""
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "INSERT INTO _yoyo_migration (migration_hash, migration_id, applied_at_utc) "
            "VALUES (?, ?, CURRENT_TIMESTAMP)",
            (f"hash-{migration_id}", migration_id),
        )


def test_assert_schema_not_ahead_noop_for_fresh_and_memory_db(tmp_path: Path) -> None:
    migrations_dir = tmp_path / "migrations"
    _write_demo_migration(migrations_dir)
    # Non-existent file, in-memory, and never-migrated DBs must all pass quietly.
    migrator.assert_schema_not_ahead(str(tmp_path / "missing.db"), migrations_dir)
    migrator.assert_schema_not_ahead(":memory:", migrations_dir)


def test_apply_pending_is_idempotent_when_db_matches_code(tmp_path: Path) -> None:
    migrations_dir = tmp_path / "migrations"
    _write_demo_migration(migrations_dir)
    db_path = tmp_path / "sessions.db"

    first = apply_pending(str(db_path), migrations_dir)
    second = apply_pending(str(db_path), migrations_dir)

    assert first == ["V001__demo"]
    assert second == []  # no SchemaAheadError — every applied id is known


def test_apply_pending_raises_when_database_is_ahead_of_code(tmp_path: Path) -> None:
    migrations_dir = tmp_path / "migrations"
    _write_demo_migration(migrations_dir)
    db_path = tmp_path / "sessions.db"

    apply_pending(str(db_path), migrations_dir)
    # A newer build applied V999 that this code's migration set does not contain.
    _record_applied_migration(db_path, "V999__from_the_future")

    with pytest.raises(migrator.SchemaAheadError, match="V999__from_the_future"):
        apply_pending(str(db_path), migrations_dir)


def test_read_applied_migration_ids_handles_missing_ledger(tmp_path: Path) -> None:
    db_path = tmp_path / "empty.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute("CREATE TABLE unrelated (id INTEGER PRIMARY KEY)")
    # No yoyo ledger table → empty set (not None, not an error).
    assert migrator._read_applied_migration_ids(db_path) == set()
