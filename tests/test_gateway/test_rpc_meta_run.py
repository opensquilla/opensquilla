"""meta.run RPC: stamps a one-shot pending /meta launch for the surface.

The handler only STAMPS a pending launch (the surface starts the turn
later); it validates the name against loaded meta-skills and respects the
master ``meta_skill.enabled`` flag. The pipeline step ``meta_command_launch``
is what later turns the stamp into ``ctx.metadata["meta_launch"]``.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from opensquilla.engine.steps.meta_command import pending_meta_launch_pop
from opensquilla.gateway.rpc.registry import RpcContext
from opensquilla.gateway.rpc_meta_runs import _handle_meta_run
from opensquilla.gateway.scopes import METHOD_SCOPES, WRITE_SCOPE
from tests.test_engine.test_runtime_meta_invoke_surfacing import _make_loader_with_meta


def _drain(session_key: str) -> None:
    """Clear any residual pending launch so each test starts clean."""
    pending_meta_launch_pop(session_key)


def _enabled_cfg(enabled: bool = True) -> SimpleNamespace:
    return SimpleNamespace(meta_skill=SimpleNamespace(enabled=enabled, auto_trigger=False))


def test_meta_run_scope_contract() -> None:
    assert METHOD_SCOPES["meta.run"] == WRITE_SCOPE


def test_meta_run_valid_invokable_skill_stamps_launch(tmp_path: Path) -> None:
    _drain("sess-run-1")
    loader = _make_loader_with_meta(tmp_path)
    ctx = RpcContext(conn_id="test", config=_enabled_cfg(), skill_loader=loader)

    payload = asyncio.run(
        _handle_meta_run({"name": "meta-tiny", "sessionKey": "sess-run-1"}, ctx)
    )

    assert payload == {"ok": True, "name": "meta-tiny", "sessionKey": "sess-run-1"}
    # Store was stamped — the next turn would pop this exact name.
    assert pending_meta_launch_pop("sess-run-1") == "meta-tiny"


def test_meta_run_accepts_key_alias(tmp_path: Path) -> None:
    _drain("sess-run-alias")
    loader = _make_loader_with_meta(tmp_path)
    ctx = RpcContext(conn_id="test", config=_enabled_cfg(), skill_loader=loader)

    payload = asyncio.run(
        _handle_meta_run({"name": "meta-tiny", "key": "sess-run-alias"}, ctx)
    )

    assert payload["ok"] is True
    assert payload["sessionKey"] == "sess-run-alias"
    assert pending_meta_launch_pop("sess-run-alias") == "meta-tiny"


def test_meta_run_unknown_name_refused_and_not_stamped(tmp_path: Path) -> None:
    _drain("sess-run-2")
    loader = _make_loader_with_meta(tmp_path)
    ctx = RpcContext(conn_id="test", config=_enabled_cfg(), skill_loader=loader)

    payload = asyncio.run(
        _handle_meta_run({"name": "nope-skill", "sessionKey": "sess-run-2"}, ctx)
    )

    assert payload["ok"] is False
    assert "nope-skill" in payload["error"]
    assert pending_meta_launch_pop("sess-run-2") is None


def test_meta_run_disable_model_invocation_refused_and_not_stamped(tmp_path: Path) -> None:
    _drain("sess-run-3")
    loader = _make_loader_with_meta(tmp_path, disable_model_invocation=True)
    ctx = RpcContext(conn_id="test", config=_enabled_cfg(), skill_loader=loader)

    payload = asyncio.run(
        _handle_meta_run({"name": "meta-tiny", "sessionKey": "sess-run-3"}, ctx)
    )

    assert payload["ok"] is False
    assert "meta-tiny" in payload["error"]
    assert pending_meta_launch_pop("sess-run-3") is None


def test_meta_run_disabled_flag_refused_and_not_stamped(tmp_path: Path) -> None:
    _drain("sess-run-4")
    loader = _make_loader_with_meta(tmp_path)
    ctx = RpcContext(
        conn_id="test",
        config={"meta_skill": {"enabled": False}},
        skill_loader=loader,
    )

    payload = asyncio.run(
        _handle_meta_run({"name": "meta-tiny", "sessionKey": "sess-run-4"}, ctx)
    )

    assert payload["ok"] is False
    assert payload.get("disabled") is True
    assert pending_meta_launch_pop("sess-run-4") is None


def test_meta_run_requires_name_and_session_key(tmp_path: Path) -> None:
    loader = _make_loader_with_meta(tmp_path)
    ctx = RpcContext(conn_id="test", config=_enabled_cfg(), skill_loader=loader)

    with pytest.raises(Exception):
        asyncio.run(_handle_meta_run({"sessionKey": "sess-x"}, ctx))
    with pytest.raises(Exception):
        asyncio.run(_handle_meta_run({"name": "meta-tiny"}, ctx))
