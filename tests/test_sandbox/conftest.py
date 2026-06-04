from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_opensquilla_state(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    state_root = tmp_path / "opensquilla-home"
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(state_root))

    from opensquilla.application import approval_queue as approval_queue_mod

    monkeypatch.setattr(
        approval_queue_mod,
        "_DEFAULT_APPROVAL_QUEUE_PATH",
        state_root / "state" / "approval_queue.sqlite",
    )
