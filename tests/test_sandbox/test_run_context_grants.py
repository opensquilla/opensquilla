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


@pytest.mark.asyncio
async def test_remove_mount_grant_normalizes_caller_path(tmp_path):
    from opensquilla.sandbox.run_context_service import (
        add_mount_grant,
        remove_mount_grant,
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

    updated = await remove_mount_grant(
        manager,
        manager.node.session_key,
        path=str(outside / "nested" / ".."),
        config=_config(),
        workspace=str(workspace),
    )

    assert updated.mounts == ()


@pytest.mark.asyncio
async def test_duplicate_mount_grant_replaces_existing_entry(tmp_path):
    from opensquilla.sandbox.run_context_service import add_mount_grant

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
    updated = await add_mount_grant(
        manager,
        manager.node.session_key,
        path=str(outside / "nested" / ".."),
        access="rw",
        scope="workspace",
        config=_config(),
        workspace=str(workspace),
    )
    assert len(updated.mounts) == 1
    assert updated.mounts[0].access == "rw"
    assert updated.mounts[0].scope == "workspace"


@pytest.mark.asyncio
async def test_duplicate_domain_grant_replaces_existing_entry(tmp_path):
    from opensquilla.sandbox.run_context_service import add_domain_grant

    manager = _SessionManager()

    await add_domain_grant(
        manager,
        manager.node.session_key,
        domain="https://pypi.org/simple",
        scope="chat",
        config=_config(),
        workspace=str(tmp_path),
    )
    updated = await add_domain_grant(
        manager,
        manager.node.session_key,
        domain="pypi.org",
        scope="workspace",
        config=_config(),
        workspace=str(tmp_path),
    )
    assert len(updated.domains) == 1
    assert updated.domains[0].scope == "workspace"


@pytest.mark.asyncio
async def test_duplicate_bundle_grant_replaces_existing_entry(tmp_path):
    from opensquilla.sandbox.run_context_service import enable_bundle_grant

    manager = _SessionManager()

    await enable_bundle_grant(
        manager,
        manager.node.session_key,
        bundle_id="python-package-install",
        scope="chat",
        config=_config(),
        workspace=str(tmp_path),
    )
    updated = await enable_bundle_grant(
        manager,
        manager.node.session_key,
        bundle_id="python-package-install",
        scope="workspace",
        config=_config(),
        workspace=str(tmp_path),
    )
    assert len(updated.bundles) == 1
    assert updated.bundles[0].scope == "workspace"


@pytest.mark.asyncio
async def test_disable_bundle_grant_removes_existing_entry(tmp_path):
    from opensquilla.sandbox.run_context_service import (
        disable_bundle_grant,
        enable_bundle_grant,
    )

    manager = _SessionManager()

    await enable_bundle_grant(
        manager,
        manager.node.session_key,
        bundle_id="python-package-install",
        scope="workspace",
        config=_config(),
        workspace=str(tmp_path),
    )
    updated = await disable_bundle_grant(
        manager,
        manager.node.session_key,
        bundle_id=" python-package-install ",
        config=_config(),
        workspace=str(tmp_path),
    )

    assert updated.bundles == ()
    assert manager.node.origin["sandbox_run_context"]["bundles"] == []


@pytest.mark.asyncio
async def test_disable_bundle_grant_rejects_unknown_without_mutation(tmp_path):
    from opensquilla.sandbox.run_context_service import (
        disable_bundle_grant,
        enable_bundle_grant,
    )

    manager = _SessionManager()
    await enable_bundle_grant(
        manager,
        manager.node.session_key,
        bundle_id="python-package-install",
        scope="workspace",
        config=_config(),
        workspace=str(tmp_path),
    )
    origin_before = manager.node.origin

    with pytest.raises(ValueError, match="unknown_package_bundle"):
        await disable_bundle_grant(
            manager,
            manager.node.session_key,
            bundle_id="python-package-intsall",
            config=_config(),
            workspace=str(tmp_path),
        )

    assert manager.node.origin is origin_before
    assert manager.node.origin["sandbox_run_context"]["bundles"] == [
        {
            "bundle_id": "python-package-install",
            "scope": "workspace",
            "source": "manual",
        }
    ]


@pytest.mark.asyncio
async def test_saved_bundle_id_payload_deserializes(tmp_path):
    from opensquilla.sandbox.run_context import get_run_context

    manager = _SessionManager()
    manager.node.origin = {
        "sandbox_run_context": {
            "run_mode": "standard",
            "workspace": str(tmp_path),
            "bundles": [{"bundleId": "python-package-install"}],
        }
    }

    ctx = await get_run_context(
        manager,
        manager.node.session_key,
        config=_config(),
        workspace=str(tmp_path),
    )

    assert ctx.bundles[0].bundle_id == "python-package-install"


@pytest.mark.asyncio
async def test_temporary_grants_round_trip(tmp_path):
    from opensquilla.sandbox.run_context import (
        RunContext,
        TemporaryGrant,
        get_run_context,
        persist_run_context,
    )
    from opensquilla.sandbox.run_mode import RunMode

    manager = _SessionManager()
    grant = TemporaryGrant(
        kind="domain",
        value="pypi.org",
        fingerprint="abc123",
        expires_after="once",
    )

    await persist_run_context(
        manager,
        manager.node.session_key,
        RunContext(
            run_mode=RunMode.STANDARD,
            workspace=str(tmp_path),
            temporary_grants=(grant,),
            source="saved",
        ),
    )
    ctx = await get_run_context(
        manager,
        manager.node.session_key,
        config=_config(),
        workspace=str(tmp_path),
    )
    payload = ctx.to_origin_payload()

    assert ctx.temporary_grants == (grant,)
    assert payload["temporary_grants"] == [
        {
            "kind": "domain",
            "value": "pypi.org",
            "fingerprint": "abc123",
            "expires_after": "once",
        }
    ]


@pytest.mark.asyncio
async def test_set_run_mode_preserves_bundle_and_temporary_grants(tmp_path):
    from opensquilla.sandbox.run_context import (
        PackageBundleGrant,
        RunContext,
        TemporaryGrant,
        persist_run_context,
        set_run_mode,
    )
    from opensquilla.sandbox.run_mode import RunMode

    manager = _SessionManager()
    bundle = PackageBundleGrant(bundle_id="python-package-install")
    temporary = TemporaryGrant(
        kind="domain",
        value="pypi.org",
        fingerprint="abc123",
    )
    await persist_run_context(
        manager,
        manager.node.session_key,
        RunContext(
            run_mode=RunMode.STANDARD,
            workspace=str(tmp_path),
            bundles=(bundle,),
            temporary_grants=(temporary,),
            source="saved",
        ),
    )

    updated = await set_run_mode(
        manager,
        manager.node.session_key,
        RunMode.TRUSTED,
        config=_config(),
        workspace=str(tmp_path),
    )

    assert updated.bundles == (bundle,)
    assert updated.temporary_grants == (temporary,)


@pytest.mark.asyncio
async def test_remove_domain_grant_rejects_invalid_domain(tmp_path):
    from opensquilla.sandbox.run_context_service import remove_domain_grant

    manager = _SessionManager()
    manager.node.origin = {
        "sandbox_run_context": {
            "run_mode": "standard",
            "domains": [{"domain": "pypi.org"}],
        }
    }

    with pytest.raises(ValueError, match="ip_literal"):
        await remove_domain_grant(
            manager,
            manager.node.session_key,
            domain="127.0.0.1",
            config=_config(),
            workspace=str(tmp_path),
        )
    assert manager.node.origin == {
        "sandbox_run_context": {
            "run_mode": "standard",
            "domains": [{"domain": "pypi.org"}],
        }
    }
