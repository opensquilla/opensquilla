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
@pytest.mark.parametrize("path_kind", ["root", "sensitive"])
async def test_remove_mount_grant_rejects_root_or_sensitive_path_without_mutation(
    tmp_path,
    path_kind,
):
    from opensquilla.sandbox.run_context_service import (
        add_mount_grant,
        remove_mount_grant,
    )

    manager = _SessionManager()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    sensitive_path = tmp_path / ".ssh" / "id_rsa"

    await add_mount_grant(
        manager,
        manager.node.session_key,
        path=str(outside),
        access="ro",
        scope="chat",
        config=_config(),
        workspace=str(workspace),
    )
    origin_before = manager.node.origin
    removal_path = "/" if path_kind == "root" else str(sensitive_path)

    with pytest.raises(ValueError, match="sensitive_path"):
        await remove_mount_grant(
            manager,
            manager.node.session_key,
            path=removal_path,
            config=_config(),
            workspace=str(workspace),
        )

    assert manager.node.origin is origin_before
    assert manager.node.origin["sandbox_run_context"]["mounts"] == [
        {"path": str(outside.resolve(strict=False)), "access": "ro", "scope": "chat"}
    ]


@pytest.mark.asyncio
async def test_absent_removals_do_not_create_saved_context(tmp_path):
    from opensquilla.sandbox.run_context_service import (
        disable_bundle_grant,
        remove_domain_grant,
        remove_mount_grant,
    )

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    manager = _SessionManager()
    await remove_mount_grant(
        manager,
        manager.node.session_key,
        path=str(outside),
        config=_config(),
        workspace=str(workspace),
    )
    assert manager.node.origin is None

    manager = _SessionManager()
    await remove_domain_grant(
        manager,
        manager.node.session_key,
        domain="pypi.org",
        config=_config(),
        workspace=str(workspace),
    )
    assert manager.node.origin is None

    manager = _SessionManager()
    await disable_bundle_grant(
        manager,
        manager.node.session_key,
        bundle_id="python-package-install",
        config=_config(),
        workspace=str(workspace),
    )
    assert manager.node.origin is None


@pytest.mark.asyncio
async def test_absent_removals_preserve_saved_origin(tmp_path):
    from opensquilla.sandbox.run_context_service import (
        disable_bundle_grant,
        remove_domain_grant,
        remove_mount_grant,
    )

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    mounted = tmp_path / "mounted"
    mounted.mkdir()
    absent_mount = tmp_path / "absent"
    absent_mount.mkdir()
    saved_origin = {
        "sandbox_run_context": {
            "run_mode": "standard",
            "workspace": str(workspace),
            "mounts": [
                {
                    "path": str(mounted),
                    "access": "ro",
                    "scope": "chat",
                }
            ],
            "domains": [
                {
                    "domain": "pypi.org",
                    "scope": "chat",
                    "source": "manual",
                }
            ],
            "bundles": [
                {
                    "bundle_id": "python-package-install",
                    "scope": "workspace",
                    "source": "manual",
                }
            ],
        }
    }

    manager = _SessionManager()
    manager.node.origin = saved_origin
    await remove_mount_grant(
        manager,
        manager.node.session_key,
        path=str(absent_mount),
        config=_config(),
        workspace=str(workspace),
    )
    assert manager.node.origin is saved_origin
    assert manager.node.origin == saved_origin

    manager = _SessionManager()
    manager.node.origin = saved_origin
    await remove_domain_grant(
        manager,
        manager.node.session_key,
        domain="files.pythonhosted.org",
        config=_config(),
        workspace=str(workspace),
    )
    assert manager.node.origin is saved_origin
    assert manager.node.origin == saved_origin

    manager = _SessionManager()
    manager.node.origin = saved_origin
    await disable_bundle_grant(
        manager,
        manager.node.session_key,
        bundle_id="node-package-install",
        config=_config(),
        workspace=str(workspace),
    )
    assert manager.node.origin is saved_origin
    assert manager.node.origin == saved_origin


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
async def test_set_workspace_normalizes_before_persisting(tmp_path):
    from opensquilla.sandbox.run_context_service import set_workspace

    manager = _SessionManager()
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    updated = await set_workspace(
        manager,
        manager.node.session_key,
        workspace_path=str(workspace / "nested" / ".."),
        config=_config(),
        current_workspace=None,
    )

    assert updated.workspace == str(workspace.resolve(strict=False))
    assert (
        manager.node.origin["sandbox_run_context"]["workspace"]
        == str(workspace.resolve(strict=False))
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("workspace_path", ["", "/"])
async def test_set_workspace_rejects_empty_or_root_paths(tmp_path, workspace_path):
    from opensquilla.sandbox.run_context_service import set_workspace

    manager = _SessionManager()

    with pytest.raises(ValueError):
        await set_workspace(
            manager,
            manager.node.session_key,
            workspace_path=workspace_path,
            config=_config(),
            current_workspace=str(tmp_path),
        )
    assert manager.node.origin is None


@pytest.mark.asyncio
async def test_set_workspace_rejects_sensitive_path(tmp_path):
    from opensquilla.sandbox.run_context_service import set_workspace

    manager = _SessionManager()

    with pytest.raises(ValueError, match="sensitive_path"):
        await set_workspace(
            manager,
            manager.node.session_key,
            workspace_path=str(tmp_path / ".ssh" / "id_rsa"),
            config=_config(),
            current_workspace=str(tmp_path),
        )
    assert manager.node.origin is None


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
async def test_saved_unknown_bundle_payload_is_ignored(tmp_path):
    from opensquilla.sandbox.run_context import get_run_context

    manager = _SessionManager()
    manager.node.origin = {
        "sandbox_run_context": {
            "run_mode": "standard",
            "workspace": str(tmp_path),
            "bundles": [
                {"bundleId": "python-package-install"},
                {"bundle_id": "unknown-package-install"},
            ],
        }
    }

    ctx = await get_run_context(
        manager,
        manager.node.session_key,
        config=_config(),
        workspace=str(tmp_path),
    )

    assert [bundle.bundle_id for bundle in ctx.bundles] == ["python-package-install"]


@pytest.mark.asyncio
async def test_saved_duplicate_bundle_payload_keeps_last_value(tmp_path):
    from opensquilla.sandbox.run_context import get_run_context

    manager = _SessionManager()
    manager.node.origin = {
        "sandbox_run_context": {
            "run_mode": "standard",
            "workspace": str(tmp_path),
            "bundles": [
                {
                    "bundle_id": "python-package-install",
                    "scope": "chat",
                    "source": "legacy",
                },
                {
                    "bundleId": " python-package-install ",
                    "scope": "workspace",
                    "source": "manual",
                },
            ],
        }
    }

    ctx = await get_run_context(
        manager,
        manager.node.session_key,
        config=_config(),
        workspace=str(tmp_path),
    )

    assert [
        (bundle.bundle_id, bundle.scope, bundle.source) for bundle in ctx.bundles
    ] == [("python-package-install", "workspace", "manual")]


@pytest.mark.asyncio
async def test_saved_root_workspace_is_dropped(tmp_path):
    from opensquilla.sandbox.run_context import get_run_context

    manager = _SessionManager()
    manager.node.origin = {
        "sandbox_run_context": {
            "run_mode": "standard",
            "workspace": "/",
        }
    }

    ctx = await get_run_context(
        manager,
        manager.node.session_key,
        config=_config(),
        workspace=str(tmp_path),
    )

    assert ctx.workspace is None


@pytest.mark.asyncio
async def test_saved_sensitive_workspace_is_dropped(tmp_path):
    from opensquilla.sandbox.run_context import get_run_context

    manager = _SessionManager()
    manager.node.origin = {
        "sandbox_run_context": {
            "run_mode": "standard",
            "workspace": str(tmp_path / ".ssh" / "id_rsa"),
        }
    }

    ctx = await get_run_context(
        manager,
        manager.node.session_key,
        config=_config(),
        workspace=str(tmp_path),
    )

    assert ctx.workspace is None


@pytest.mark.asyncio
async def test_saved_sensitive_mount_is_dropped_while_valid_mount_remains(tmp_path):
    from opensquilla.sandbox.run_context import get_run_context

    valid = tmp_path / "outside"
    valid.mkdir()
    manager = _SessionManager()
    manager.node.origin = {
        "sandbox_run_context": {
            "run_mode": "standard",
            "mounts": [
                {"path": str(tmp_path / ".ssh" / "id_rsa"), "access": "ro"},
                {"path": str(valid), "access": "rw", "scope": "workspace"},
            ],
        }
    }

    ctx = await get_run_context(
        manager,
        manager.node.session_key,
        config=_config(),
        workspace=str(tmp_path / "workspace"),
    )

    assert [(mount.path, mount.access, mount.scope) for mount in ctx.mounts] == [
        (str(valid.resolve(strict=False)), "rw", "workspace")
    ]


@pytest.mark.asyncio
async def test_saved_invalid_domain_is_dropped_while_valid_domain_normalizes(tmp_path):
    from opensquilla.sandbox.run_context import get_run_context

    manager = _SessionManager()
    manager.node.origin = {
        "sandbox_run_context": {
            "run_mode": "standard",
            "domains": [
                {"domain": "127.0.0.1"},
                {"domain": "HTTPS://PyPI.org/simple", "scope": "workspace"},
            ],
        }
    }

    ctx = await get_run_context(
        manager,
        manager.node.session_key,
        config=_config(),
        workspace=str(tmp_path),
    )

    assert [(domain.domain, domain.scope) for domain in ctx.domains] == [
        ("pypi.org", "workspace")
    ]


@pytest.mark.asyncio
async def test_saved_duplicate_mounts_and_domains_keep_normalized_last_value(tmp_path):
    from opensquilla.sandbox.run_context import get_run_context

    outside = tmp_path / "outside"
    outside.mkdir()
    manager = _SessionManager()
    manager.node.origin = {
        "sandbox_run_context": {
            "run_mode": "standard",
            "mounts": [
                {"path": str(outside), "access": "ro", "scope": "chat"},
                {
                    "path": str(outside / "nested" / ".."),
                    "access": "rw",
                    "scope": "workspace",
                },
            ],
            "domains": [
                {"domain": "HTTPS://PyPI.org/simple", "scope": "chat"},
                {"domain": "pypi.org", "scope": "workspace", "source": "manual"},
            ],
        }
    }

    ctx = await get_run_context(
        manager,
        manager.node.session_key,
        config=_config(),
        workspace=str(tmp_path),
    )

    assert [(mount.path, mount.access, mount.scope) for mount in ctx.mounts] == [
        (str(outside.resolve(strict=False)), "rw", "workspace")
    ]
    assert [(domain.domain, domain.scope, domain.source) for domain in ctx.domains] == [
        ("pypi.org", "workspace", "manual")
    ]


@pytest.mark.asyncio
async def test_unrelated_mutation_does_not_repersist_unsafe_saved_entries(tmp_path):
    from opensquilla.sandbox.run_context_service import enable_bundle_grant

    valid_mount = tmp_path / "outside"
    valid_mount.mkdir()
    manager = _SessionManager()
    manager.node.origin = {
        "sandbox_run_context": {
            "run_mode": "standard",
            "workspace": "/",
            "mounts": [
                {"path": str(tmp_path / ".ssh" / "id_rsa"), "access": "ro"},
                {"path": str(valid_mount), "access": "rw"},
            ],
            "domains": [
                {"domain": "127.0.0.1"},
                {"domain": "HTTPS://PyPI.org/simple"},
            ],
        }
    }

    await enable_bundle_grant(
        manager,
        manager.node.session_key,
        bundle_id="python-package-install",
        scope="workspace",
        config=_config(),
        workspace=str(tmp_path),
    )

    saved = manager.node.origin["sandbox_run_context"]
    assert saved["workspace"] is None
    assert saved["mounts"] == [
        {"path": str(valid_mount.resolve(strict=False)), "access": "rw", "scope": "chat"}
    ]
    assert saved["domains"] == [
        {"domain": "pypi.org", "scope": "chat", "source": "manual"}
    ]
    assert saved["bundles"] == [
        {
            "bundle_id": "python-package-install",
            "scope": "workspace",
            "source": "manual",
        }
    ]


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
