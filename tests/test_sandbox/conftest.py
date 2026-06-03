from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_opensquilla_state(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(tmp_path / "opensquilla-home"))
