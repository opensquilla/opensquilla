"""router.selflearning.status RPC handler."""

from __future__ import annotations

import numpy as np
import pytest

from opensquilla.gateway.config import (
    GatewayConfig,
    RouterSelfLearningConfig,
)
from opensquilla.gateway.rpc import RpcContext, get_dispatcher
from opensquilla.gateway.rpc_router import _handle_selflearning_status
from opensquilla.gateway.scopes import METHOD_SCOPES, READ_SCOPE
from opensquilla.squilla_router.self_learning import encode_features, write_sample
from opensquilla.squilla_router.self_learning.promotion import write_active_atomic
from opensquilla.squilla_router.self_learning.schema import RouterTrainSample
from opensquilla.squilla_router.self_learning.state import TrainState, save_train_state


def _config(
    *,
    sl_enabled: bool,
    dream_enabled: bool = False,
    auto_schedule: bool = False,
) -> GatewayConfig:
    cfg = GatewayConfig()
    cfg.squilla_router.self_learning = RouterSelfLearningConfig(enabled=sl_enabled)
    cfg.memory.dream.enabled = dream_enabled
    cfg.memory.dream.auto_schedule = auto_schedule
    return cfg


def _sample(i: int, *, complaint: bool = False) -> RouterTrainSample:
    return RouterTrainSample(
        session_key="s1",
        turn_index=i,
        ts=f"2026-06-01T00:00:{i:02d}Z",
        feature_schema_version="v1",
        features_390_b64=encode_features(np.zeros(390, np.float32)),
        route_class="R0",
        final_route_class="R1" if complaint else "R0",
        complaint_detected=complaint,
    )


async def test_status_disabled_is_minimal() -> None:
    payload = await _handle_selflearning_status(
        {}, RpcContext(conn_id="t", config=_config(sl_enabled=False))
    )
    assert payload["enabled"] is False
    assert payload["trainingReachable"] is False
    assert payload["samples"] is None and payload["gate"] is None
    assert payload["activeModel"]["kind"] == "baseline"


async def test_status_flags_unreachable_training_when_dream_off(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(tmp_path))
    payload = await _handle_selflearning_status(
        {},
        RpcContext(conn_id="t", config=_config(sl_enabled=True, dream_enabled=False)),
    )
    assert payload["enabled"] is True
    assert payload["trainingReachable"] is False
    assert payload["dream"] == {
        "enabled": False,
        "autoSchedule": False,
        "killSwitchActive": False,
    }


async def test_status_reports_samples_gate_and_active_model(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(tmp_path))
    for i in range(5):
        write_sample(_sample(i, complaint=(i < 2)), "main", home=tmp_path)
    save_train_state(
        TrainState(active_version="v7", promoted_at="2026-06-01T00:00:00Z"),
        "main",
        tmp_path,
    )
    write_active_atomic("learned/v7", tmp_path)

    payload = await _handle_selflearning_status(
        {},
        RpcContext(
            conn_id="t",
            config=_config(sl_enabled=True, dream_enabled=True, auto_schedule=True),
        ),
    )
    assert payload["trainingReachable"] is True
    assert payload["samples"]["total"] == 5
    assert payload["samples"]["highValue"] == 2
    assert payload["gate"]["wouldTrain"] is False  # nowhere near the volume gate
    # Verbatim gate reason codes are a client contract (localized in the UI).
    # The samples are dated 2026-06-01 (idle gate passes), and 2 high-value
    # samples are far below the 200 default -> the volume gate trips.
    assert payload["gate"]["reason"] == "insufficient_data"
    assert payload["activeModel"] == {
        "kind": "learned",
        "version": "v7",
        "promotedAt": "2026-06-01T00:00:00Z",
    }


async def test_status_rejects_free_text_agent_id() -> None:
    ctx = RpcContext(conn_id="t", config=_config(sl_enabled=False))
    res = await get_dispatcher().dispatch(
        "r1", "router.selflearning.status", {"agentId": "not a token!!"}, ctx
    )
    assert res.error is not None


def test_status_scope_is_read() -> None:
    assert METHOD_SCOPES["router.selflearning.status"] == READ_SCOPE
    assert "router.selflearning.status" in get_dispatcher().methods()


async def test_status_never_errors_on_broken_state(tmp_path, monkeypatch) -> None:
    """A corrupt state file degrades to a partial payload, not an RPC error."""
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(tmp_path))
    state_dir = tmp_path / "router" / "data" / "main"
    state_dir.mkdir(parents=True)
    (state_dir / ".train_state.json").write_text("{not json", encoding="utf-8")
    (state_dir / "samples-2026-06.jsonl").write_text("{also broken\n", encoding="utf-8")

    payload = await _handle_selflearning_status(
        {},
        RpcContext(
            conn_id="t",
            config=_config(sl_enabled=True, dream_enabled=True, auto_schedule=True),
        ),
    )
    assert payload["enabled"] is True  # degraded, never raised


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-q"])


async def test_status_includes_feedback_block(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(tmp_path))
    from opensquilla.squilla_router.self_learning.feedback import write_feedback

    for i in range(5):
        write_sample(_sample(i), "main", home=tmp_path)
    write_feedback(
        "main",
        decision_id="f1",
        session_key="agent:main:webchat:s1",
        turn_index=0,
        rating="down",
        home=tmp_path,
    )
    write_feedback(
        "main",
        decision_id="f2",
        session_key="agent:main:webchat:s1",
        turn_index=1,
        rating="down",
        executed_kind="ensemble",
        home=tmp_path,
    )

    payload = await _handle_selflearning_status(
        {},
        RpcContext(
            conn_id="t",
            config=_config(sl_enabled=True, dream_enabled=True, auto_schedule=True),
        ),
    )
    assert payload["samples"]["feedback"] == {"up": 0, "down": 2, "downSingle": 1}
