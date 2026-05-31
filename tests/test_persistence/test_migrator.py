from __future__ import annotations

import builtins
import contextlib
import warnings
from pathlib import Path
from types import SimpleNamespace

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
