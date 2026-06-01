from __future__ import annotations

from types import SimpleNamespace

import pytest

from opensquilla.sandbox.run_mode import RunMode


class _SessionManager:
    def __init__(self):
        self.node = SimpleNamespace(
            session_key="agent:main:webchat:abc",
            origin=None,
        )

    async def get_session(self, session_key: str):
        return self.node if session_key == self.node.session_key else None

    async def update(self, session_key: str, **fields):
        for key, value in fields.items():
            setattr(self.node, key, value)
        return self.node


@pytest.mark.asyncio
async def test_run_context_initializes_from_global_default_and_persists_override() -> None:
    from opensquilla.sandbox.run_context import get_run_context, set_run_mode

    manager = _SessionManager()
    config = SimpleNamespace(
        sandbox=SimpleNamespace(run_mode="standard", sandbox=True, security_grading=True),
        permissions=SimpleNamespace(default_mode="off"),
    )

    ctx = await get_run_context(
        manager,
        manager.node.session_key,
        config=config,
        workspace="/tmp/ws",
    )
    assert ctx.run_mode == RunMode.STANDARD
    assert ctx.source == "default"

    updated = await set_run_mode(manager, manager.node.session_key, RunMode.TRUSTED, config=config)
    assert updated.run_mode == RunMode.TRUSTED
    assert manager.node.origin["sandbox_run_context"]["run_mode"] == "trusted"


@pytest.mark.asyncio
async def test_set_run_mode_persists_first_workspace_and_preserves_origin_keys() -> None:
    from opensquilla.sandbox.run_context import set_run_mode

    manager = _SessionManager()
    manager.node.origin = {"other": {"kept": True}}
    config = SimpleNamespace(
        sandbox=SimpleNamespace(run_mode="standard", sandbox=True, security_grading=True),
        permissions=SimpleNamespace(default_mode="off"),
    )

    updated = await set_run_mode(
        manager,
        manager.node.session_key,
        RunMode.TRUSTED,
        config=config,
        workspace="/tmp/ws",
    )

    assert updated.workspace == "/tmp/ws"
    assert manager.node.origin["other"] == {"kept": True}
    assert manager.node.origin["sandbox_run_context"]["workspace"] == "/tmp/ws"


@pytest.mark.asyncio
async def test_saved_context_wins_over_later_global_default() -> None:
    from opensquilla.sandbox.run_context import get_run_context

    manager = _SessionManager()
    manager.node.origin = {"sandbox_run_context": {"run_mode": "standard", "workspace": "/tmp/old"}}
    config = SimpleNamespace(
        sandbox=SimpleNamespace(run_mode="full", sandbox=False, security_grading=False),
        permissions=SimpleNamespace(default_mode="full"),
    )

    ctx = await get_run_context(
        manager,
        manager.node.session_key,
        config=config,
        workspace="/tmp/new",
    )

    assert ctx.run_mode == RunMode.STANDARD
    assert ctx.workspace == "/tmp/old"
    assert ctx.source == "saved"


@pytest.mark.asyncio
async def test_rpc_run_context_get_reports_missing_session() -> None:
    from opensquilla.gateway.auth import Principal
    from opensquilla.gateway.rpc import RpcContext
    from opensquilla.gateway.rpc_sandbox import _handle_sandbox_run_context_get

    manager = _SessionManager()
    config = SimpleNamespace(
        workspace_dir="/tmp/ws",
        agents=[],
        sandbox=SimpleNamespace(run_mode="standard", sandbox=True, security_grading=True),
        permissions=SimpleNamespace(default_mode="off"),
    )
    ctx = RpcContext(
        conn_id="c",
        principal=Principal(
            role="operator",
            scopes=frozenset(["operator.read"]),
            is_owner=True,
            authenticated=True,
        ),
        session_manager=manager,
        config=config,
    )

    with pytest.raises(KeyError, match="Session not found"):
        await _handle_sandbox_run_context_get(
            {"sessionKey": "agent:main:webchat:missing"},
            ctx,
        )
