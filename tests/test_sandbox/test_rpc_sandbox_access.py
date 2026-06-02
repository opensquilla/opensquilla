from __future__ import annotations

from types import SimpleNamespace

import pytest


class _SessionManager:
    def __init__(self):
        self.node = SimpleNamespace(
            session_key="agent:main:webchat:abc",
            agent_id="main",
            origin=None,
        )
        self.sessions = {self.node.session_key: self.node}

    async def get_session(self, session_key: str):
        return self.sessions.get(session_key)

    async def get_or_create(self, session_key: str, agent_id: str = "main", **kwargs):
        return self.sessions[session_key], False

    async def update(self, session_key: str, **fields):
        node = self.sessions[session_key]
        for key, value in fields.items():
            setattr(node, key, value)
        return node


def _ctx(manager: _SessionManager, *, is_owner: bool = True):
    from opensquilla.gateway.auth import Principal
    from opensquilla.gateway.rpc import RpcContext

    config = SimpleNamespace(
        workspace_dir="/tmp/ws",
        agents=[],
        sandbox=SimpleNamespace(
            run_mode="standard",
            sandbox=True,
            security_grading=True,
            backend="noop",
            network_default="proxy_allowlist",
        ),
        permissions=SimpleNamespace(default_mode="off"),
    )
    return RpcContext(
        conn_id="c",
        principal=Principal(
            role="operator",
            scopes=frozenset(["operator.read", "operator.write"]),
            is_owner=is_owner,
            authenticated=True,
        ),
        session_manager=manager,
        config=config,
    )


@pytest.mark.asyncio
async def test_rpc_add_domain_returns_updated_context() -> None:
    from opensquilla.gateway.rpc_sandbox import _handle_sandbox_domain_add

    manager = _SessionManager()

    result = await _handle_sandbox_domain_add(
        {
            "sessionKey": manager.node.session_key,
            "domain": "https://pypi.org/simple",
            "scope": "workspace",
        },
        _ctx(manager),
    )

    assert result["domains"] == [
        {"domain": "pypi.org", "scope": "workspace", "source": "manual"}
    ]


@pytest.mark.asyncio
async def test_rpc_add_mount_rejects_non_owner() -> None:
    from opensquilla.gateway.rpc import RpcHandlerError
    from opensquilla.gateway.rpc_sandbox import _handle_sandbox_mount_add

    manager = _SessionManager()

    with pytest.raises(RpcHandlerError, match="requires owner principal"):
        await _handle_sandbox_mount_add(
            {"sessionKey": manager.node.session_key, "path": "/tmp/ws/extras"},
            _ctx(manager, is_owner=False),
        )

    assert manager.node.origin is None


@pytest.mark.asyncio
async def test_rpc_run_context_get_includes_bundles_and_temporary_grants() -> None:
    from opensquilla.gateway.rpc_sandbox import _handle_sandbox_run_context_get
    from opensquilla.sandbox.run_context import (
        PackageBundleGrant,
        RunContext,
        TemporaryGrant,
        persist_run_context,
    )
    from opensquilla.sandbox.run_mode import RunMode

    manager = _SessionManager()
    await persist_run_context(
        manager,
        manager.node.session_key,
        RunContext(
            run_mode=RunMode.STANDARD,
            workspace="/tmp/ws",
            bundles=(PackageBundleGrant(bundle_id="python-package-install"),),
            temporary_grants=(
                TemporaryGrant(
                    kind="domain",
                    value="pypi.org",
                    fingerprint="abc123",
                ),
            ),
            source="saved",
        ),
    )

    result = await _handle_sandbox_run_context_get(
        {"sessionKey": manager.node.session_key},
        _ctx(manager),
    )

    assert result["bundles"] == [
        {
            "bundle_id": "python-package-install",
            "scope": "workspace",
            "source": "manual",
        }
    ]
    assert result["temporaryGrants"] == [
        {
            "kind": "domain",
            "value": "pypi.org",
            "fingerprint": "abc123",
            "expires_after": "once",
        }
    ]


@pytest.mark.asyncio
async def test_rpc_sandbox_status_reports_backend_managed_network_and_run_mode() -> None:
    from opensquilla.gateway.rpc_sandbox import _handle_sandbox_status

    manager = _SessionManager()

    result = await _handle_sandbox_status({}, _ctx(manager))

    assert result["run_mode"] == "standard"
    assert result["run_mode_label"] == "Standard-Sandbox"
    assert result["execution_target"] == "sandbox"
    assert result["posture"] == "standard"
    assert result["backend"] == "noop"
    assert result["managed_network"] == "ready"
    assert result["sandbox"] == {
        "sandbox": True,
        "security_grading": True,
        "network_default": "proxy_allowlist",
    }
    assert result["permissions"] == {"default_mode": "off"}


@pytest.mark.asyncio
async def test_rpc_sandbox_explain_returns_status_messages_and_optional_context() -> None:
    from opensquilla.gateway.rpc_sandbox import _handle_sandbox_explain
    from opensquilla.sandbox.run_context import RunContext, persist_run_context
    from opensquilla.sandbox.run_mode import RunMode

    manager = _SessionManager()
    await persist_run_context(
        manager,
        manager.node.session_key,
        RunContext(run_mode=RunMode.TRUSTED, workspace="/tmp/ws", source="saved"),
    )

    result = await _handle_sandbox_explain(
        {"sessionKey": manager.node.session_key},
        _ctx(manager),
    )

    assert result["status"]["run_mode"] == "standard"
    assert result["runContext"]["runMode"] == "trusted"
    assert result["messages"] == [
        {"kind": "run_mode", "message": "Run mode is standard."},
        {
            "kind": "managed_network",
            "message": "Managed network allowlist is ready.",
        },
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handler_name", "params"),
    [
        ("_handle_sandbox_workspace_set", {"workspace": "/tmp/ws/project"}),
        ("_handle_sandbox_mount_remove", {"path": "/tmp/ws/extras"}),
        ("_handle_sandbox_domain_add", {"domain": "pypi.org"}),
        ("_handle_sandbox_domain_remove", {"domain": "pypi.org"}),
        ("_handle_sandbox_bundle_enable", {"bundleId": "python-package-install"}),
        ("_handle_sandbox_bundle_disable", {"bundleId": "python-package-install"}),
    ],
)
async def test_rpc_sandbox_mutations_reject_non_owner(
    handler_name: str,
    params: dict[str, str],
) -> None:
    from opensquilla.gateway.rpc import RpcHandlerError
    import opensquilla.gateway.rpc_sandbox as rpc_sandbox

    manager = _SessionManager()
    handler = getattr(rpc_sandbox, handler_name)

    with pytest.raises(RpcHandlerError, match="requires owner principal"):
        await handler(
            {"sessionKey": manager.node.session_key, **params},
            _ctx(manager, is_owner=False),
        )

    assert manager.node.origin is None
