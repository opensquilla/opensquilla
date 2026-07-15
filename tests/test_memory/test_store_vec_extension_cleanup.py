from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from opensquilla.memory.store import LongTermMemoryStore


class _FakeDb:
    def __init__(self) -> None:
        self.extension_states: list[bool] = []

    async def enable_load_extension(self, enabled: bool) -> None:
        self.extension_states.append(enabled)

    async def load_extension(self, path: str) -> None:
        raise OSError("load failed")


@pytest.mark.asyncio
async def test_probe_vec_disables_extension_loading_after_load_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _FakeDb()
    store = LongTermMemoryStore(":memory:")
    store._db = db  # type: ignore[assignment]
    monkeypatch.setitem(sys.modules, "sqlite_vec", SimpleNamespace(loadable_path=lambda: "vec"))

    await store._probe_vec_extension()

    assert db.extension_states == [True, False]
    assert store.vec_available is False
