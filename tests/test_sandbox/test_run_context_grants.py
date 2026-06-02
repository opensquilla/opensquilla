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

    async def get_session(self, session_key: str):
        return self.node if session_key == self.node.session_key else None

    async def update(self, session_key: str, **fields):
        for key, value in fields.items():
            setattr(self.node, key, value)
        return self.node


def _config():
    return SimpleNamespace(
        sandbox=SimpleNamespace(run_mode="standard", sandbox=True, security_grading=True),
        permissions=SimpleNamespace(default_mode="off"),
    )


@pytest.mark.asyncio
async def test_mount_domain_and_bundle_grants_persist(tmp_path):
    from opensquilla.sandbox.run_context import get_run_context
    from opensquilla.sandbox.run_context_service import (
        add_domain_grant,
        add_mount_grant,
        enable_bundle_grant,
    )

    manager = _SessionManager()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    await add_mount_grant(
        manager,
        manager.node.session_key,
        path=str(outside),
        access="ro",
        scope="chat",
        config=_config(),
        workspace=str(workspace),
    )
    await add_domain_grant(
        manager,
        manager.node.session_key,
        domain="HTTPS://PyPI.org/simple",
        scope="workspace",
        config=_config(),
        workspace=str(workspace),
    )
    await enable_bundle_grant(
        manager,
        manager.node.session_key,
        bundle_id="python-package-install",
        scope="workspace",
        config=_config(),
        workspace=str(workspace),
    )

    ctx = await get_run_context(
        manager,
        manager.node.session_key,
        config=_config(),
        workspace=str(workspace),
    )
    assert ctx.mounts[0].path == str(outside.resolve(strict=False))
    assert ctx.mounts[0].access == "ro"
    assert ctx.domains[0].domain == "pypi.org"
    assert ctx.bundles[0].bundle_id == "python-package-install"


@pytest.mark.asyncio
async def test_sensitive_mount_is_rejected(tmp_path):
    from opensquilla.sandbox.run_context_service import add_mount_grant

    manager = _SessionManager()
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    with pytest.raises(ValueError, match="sensitive_path"):
        await add_mount_grant(
            manager,
            manager.node.session_key,
            path=str(tmp_path / ".ssh" / "id_rsa"),
            access="ro",
            scope="chat",
            config=_config(),
            workspace=str(workspace),
        )
